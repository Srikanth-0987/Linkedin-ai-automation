from __future__ import annotations

import time
from typing import Any, Optional
from pathlib import Path
import requests
from loguru import logger

from src.config import Config, config as default_config, redact_secret
from src.db import Database
from src.image_generator import ImageValidator


class PublisherError(Exception):
    """Base exception for publisher errors."""


class PublishingDisabledError(PublisherError):
    """Raised when live publishing is disabled by configuration."""


class UnapprovedPostError(PublisherError):
    """Raised when a post draft has not been approved."""


class DuplicatePostError(PublisherError):
    """Raised when attempting to publish a post that has already been published."""


class TokenExpiredError(PublisherError):
    """Raised when the LinkedIn access token is expired or missing."""


class LinkedInAPIError(PublisherError):
    """Raised when LinkedIn API returns an error response."""

    def __init__(self, status_code: int, message: str, details: Optional[dict] = None) -> None:
        super().__init__(f"LinkedIn API error [{status_code}]: {message}")
        self.status_code = status_code
        self.details = details or {}


class LinkedInPublisher:
    """Publishes organic LinkedIn posts with images using official REST APIs."""

    POSTS_API_URL = "https://api.linkedin.com/rest/posts"
    IMAGES_API_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"

    def __init__(self, cfg: Optional[Config] = None, db: Optional[Database] = None) -> None:
        self.config = cfg or default_config
        self.db = db or Database(self.config.database_path)

    def _resolve_author_urn(self, token_record: Optional[dict[str, Any]]) -> str:
        """Resolve member author URN in the form urn:li:person:{id}."""
        member_id = self.config.linkedin_member_id
        if not member_id and token_record:
            member_id = token_record.get("member_id", "")

        if not member_id:
            raise PublisherError(
                "Cannot publish: Member ID is unknown. Please run OAuth authorization first "
                "or set LINKEDIN_MEMBER_ID in .env."
            )

        if member_id.startswith("urn:li:"):
            return member_id
        return f"urn:li:person:{member_id}"

    def _get_access_token(self) -> tuple[str, Optional[dict[str, Any]]]:
        """Retrieve valid access token from environment or database.
        
        Returns:
            (access_token, token_record)
        """
        if self.config.linkedin_access_token:
            return self.config.linkedin_access_token, None

        token_record = self.db.get_token()
        if not token_record or not token_record.get("access_token"):
            raise TokenExpiredError(
                "No LinkedIn access token found. Please run OAuth login via CLI (`python -m src.cli login`) "
                "or configure LINKEDIN_ACCESS_TOKEN in .env."
            )

        now = time.time()
        if now > (token_record["expires_at"] - 300):
            raise TokenExpiredError(
                f"LinkedIn access token expired on {time.ctime(token_record['expires_at'])}. "
                "Please re-authenticate your LinkedIn account."
            )

        return token_record["access_token"], token_record

    def _upload_image(self, image_path: str, author_urn: str, access_token: str) -> str:
        """Upload a local PNG image using the official LinkedIn Images REST API.
        
        Steps:
        1. Initialize upload via POST /rest/images?action=initializeUpload
        2. Stream binary image bytes via PUT uploadUrl
        3. Return the registered image URN (urn:li:image:...)
        """
        path = Path(image_path)
        if not path.exists():
            raise PublisherError(f"Image file to upload does not exist: {path}")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": self.config.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        init_payload = {
            "initializeUploadRequest": {
                "owner": author_urn,
            }
        }

        logger.info(f"Initializing LinkedIn image upload for {path.name} (owner: {author_urn})...")

        try:
            init_resp = requests.post(
                self.IMAGES_API_URL,
                json=init_payload,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            raise PublisherError(f"Failed to connect to LinkedIn Images initializeUpload: {e}") from e

        if init_resp.status_code != 200:
            err_details = {}
            try:
                err_details = init_resp.json()
            except Exception:
                pass
            raise LinkedInAPIError(
                init_resp.status_code,
                f"Image upload initialization failed: {err_details.get('message', init_resp.text)}",
                err_details,
            )

        init_data = init_resp.json().get("value", {})
        upload_url = init_data.get("uploadUrl")
        image_urn = init_data.get("image")

        if not upload_url or not image_urn:
            raise PublisherError(f"LinkedIn Images API response missing uploadUrl or image URN: {init_resp.text}")

        logger.info(f"Uploading image binary ({path.stat().st_size} bytes) to LinkedIn storage...")

        try:
            with open(path, "rb") as f:
                upload_data = f.read()

            put_headers = {
                "Content-Type": "image/png",
            }
            put_resp = requests.put(upload_url, data=upload_data, headers=put_headers, timeout=60)
        except requests.RequestException as e:
            raise PublisherError(f"Failed to stream image binary to LinkedIn: {e}") from e

        if put_resp.status_code not in (200, 201):
            raise LinkedInAPIError(
                put_resp.status_code,
                f"Binary image upload to uploadUrl returned HTTP {put_resp.status_code}: {put_resp.text}",
            )

        logger.info(f"Successfully uploaded image to LinkedIn! Image URN: {image_urn}")
        return image_urn

    def publish_post(self, post_id: int) -> dict[str, Any]:
        """Publish a post with attached image to LinkedIn with strict safety checks.
        
        Enforces:
        - Post existence and approval validation
        - Image existence and quality validation (Feature 4 & 5)
        - Duplicate prevention
        - DRY_RUN mode (simulates and logs without network call)
        - PUBLISH_ENABLED check (blocks live calls if disabled)
        - Token expiry verification
        - Idempotent database status updates
        """
        post = self.db.get_post(post_id)
        if not post:
            raise PublisherError(f"Post #{post_id} not found in database.")

        # Safety Gate 1: Check if already published (Duplicate Prevention)
        if post["status"] == "PUBLISHED" or post.get("linkedin_post_id"):
            raise DuplicatePostError(
                f"Post #{post_id} has already been published to LinkedIn "
                f"(LinkedIn Post ID: {post.get('linkedin_post_id')}). Refusing duplicate publish."
            )

        # Safety Gate 2: Approval Requirement
        if self.config.require_approval and post["status"] != "APPROVED":
            raise UnapprovedPostError(
                f"Post #{post_id} status is '{post['status']}'. REQUIRE_APPROVAL is enabled. "
                f"Approve this post first using: python -m src.cli approve {post_id}"
            )

        # Feature 4 & 5: Image Quality Control Check (if image attached)
        image_path = post.get("image_path")
        has_image = bool(image_path and str(image_path).strip())

        if has_image:
            is_valid, reason = ImageValidator.validate(image_path)
            if not is_valid:
                self.db.mark_post_failed(post_id, f"Image quality check failed: {reason}")
                raise PublisherError(
                    f"Post #{post_id} image failed pre-publication quality check: {reason}. "
                    f"Draft preserved for review; will not publish post with broken image."
                )

        # Resolve credentials & author URN
        access_token, token_record = self._get_access_token()
        author_urn = self._resolve_author_urn(token_record)

        # Safety Gate 3: DRY RUN Mode (Full simulation)
        if self.config.dry_run:
            simulated_image_urn = f"urn:li:image:simulated_{post_id}_{int(time.time())}" if has_image else None
            simulated_payload: dict[str, Any] = {
                "author": author_urn,
                "commentary": post["commentary"],
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            if has_image:
                simulated_payload["content"] = {
                    "media": {
                        "title": post.get("topic") or "Technical Overview",
                        "id": simulated_image_urn,
                        "altText": post.get("image_alt_text") or f"Infographic on {post.get('topic')}",
                    }
                }
            logger.warning(
                f"[DRY RUN] Simulating LinkedIn post #{post_id} publish ({'with image' if has_image else 'text-only scripted'}). "
                f"Author: {author_urn}, Commentary: {post['commentary'][:60]}..."
            )
            return {
                "success": True,
                "dry_run": True,
                "post_id": post_id,
                "author": author_urn,
                "image_path": image_path if has_image else None,
                "image_urn": simulated_image_urn,
                "commentary": post["commentary"],
                "payload": simulated_payload,
                "message": f"Dry-run completed successfully ({'with image' if has_image else 'scripted text-only'}). No changes were made to LinkedIn.",
            }

        # Safety Gate 4: Live Publishing Enabled Check
        if not self.config.publish_enabled:
            logger.warning("[SAFETY BLOCK] Live publishing is disabled (PUBLISH_ENABLED=false).")
            raise PublishingDisabledError(
                "Live publishing is currently disabled (PUBLISH_ENABLED=false in config). "
                "Set PUBLISH_ENABLED=true in .env to allow live publication."
            )

        # Step 1: Upload image to LinkedIn Images API (if image attached)
        image_urn = None
        if has_image:
            image_urn = post.get("image_urn")
            if not image_urn:
                try:
                    image_urn = self._upload_image(image_path, author_urn, access_token)
                    self.db.update_post_image_urn(post_id, image_urn)
                except Exception as e:
                    self.db.mark_post_failed(post_id, f"Image upload failed: {e}")
                    raise

        # Step 2: Construct official payload for LinkedIn REST Posts API
        payload: dict[str, Any] = {
            "author": author_urn,
            "commentary": post["commentary"],
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if has_image and image_urn:
            payload["content"] = {
                "media": {
                    "title": post.get("topic") or "Technical Overview",
                    "id": image_urn,
                    "altText": post.get("image_alt_text") or f"Infographic on {post.get('topic')}",
                }
            }

        # Construct headers for official REST Posts API
        headers = {
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": self.config.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

        logger.info(
            f"Sending live post #{post_id} ({'with image' if has_image else 'scripted text-only'}) to LinkedIn (API version: {self.config.linkedin_api_version})"
        )

        try:
            response = requests.post(
                self.POSTS_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
        except requests.Timeout as e:
            err_msg = "Request timed out while connecting to LinkedIn Posts API. Outcome unknown - will not retry automatically."
            logger.error(err_msg)
            self.db.mark_post_failed(post_id, err_msg)
            raise PublisherError(err_msg) from e
        except requests.RequestException as e:
            err_msg = f"Network connection error to LinkedIn Posts API: {e}"
            logger.error(err_msg)
            self.db.mark_post_failed(post_id, err_msg)
            raise PublisherError(err_msg) from e

        # Handle API Responses
        if response.status_code == 201:
            linkedin_post_urn = response.headers.get("x-restli-id", "")
            if not linkedin_post_urn:
                try:
                    resp_json = response.json()
                    linkedin_post_urn = resp_json.get("id", "")
                except Exception:
                    linkedin_post_urn = f"urn:li:share:created_{int(time.time())}"

            logger.info(f"Successfully published post #{post_id} with image to LinkedIn! Post URN: {linkedin_post_urn}")
            self.db.mark_post_published(post_id, linkedin_post_id=linkedin_post_urn, linkedin_urn=author_urn)

            return {
                "success": True,
                "dry_run": False,
                "post_id": post_id,
                "linkedin_post_id": linkedin_post_urn,
                "image_urn": image_urn,
                "published_at": time.time(),
            }

        # Handle error responses
        error_details = {}
        try:
            error_details = response.json()
        except Exception:
            pass

        error_message = error_details.get("message", response.text)

        if response.status_code == 401:
            err_str = "LinkedIn authentication failed (401 Unauthorized). Access token may be expired or revoked."
            self.db.mark_post_failed(post_id, err_str)
            raise TokenExpiredError(err_str)

        if response.status_code == 403:
            err_str = (
                f"LinkedIn permission denied (403 Forbidden). Ensure your developer app has "
                f"'Share on LinkedIn' product and 'w_member_social' scope granted. Details: {error_message}"
            )
            self.db.mark_post_failed(post_id, err_str)
            raise LinkedInAPIError(403, err_str, error_details)

        if response.status_code == 429:
            err_str = f"LinkedIn rate limit reached (429 Too Many Requests). Details: {error_message}"
            self.db.mark_post_failed(post_id, err_str)
            raise LinkedInAPIError(429, err_str, error_details)

        err_str = f"LinkedIn returned HTTP {response.status_code}: {error_message}"
        self.db.mark_post_failed(post_id, err_str)
        raise LinkedInAPIError(response.status_code, err_str, error_details)
