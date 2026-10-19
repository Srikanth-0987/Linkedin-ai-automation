"""LinkedIn OAuth 2.0 flow implementation.

Follows official LinkedIn OAuth 2.0 and OpenID Connect documentation.
Endpoints:
- Authorization: https://www.linkedin.com/oauth/v2/authorization
- Access Token: https://www.linkedin.com/oauth/v2/accessToken
- Userinfo (Identity): https://api.linkedin.com/v2/userinfo
"""

from __future__ import annotations

import secrets
import urllib.parse
from typing import Any, Optional
import requests
from loguru import logger

from src.config import Config, config as default_config, redact_secret
from src.db import Database


class OAuthError(Exception):
    """Base exception for OAuth failures."""


class StateValidationError(OAuthError):
    """Raised when CSRF state validation fails."""


class AuthorizationDeniedError(OAuthError):
    """Raised when the user denies authorization."""


class TokenExchangeError(OAuthError):
    """Raised when token exchange fails."""


class UserinfoError(OAuthError):
    """Raised when retrieving member identity fails."""


class LinkedInOAuth:
    """Manages LinkedIn OAuth 2.0 3-legged authorization and member identity."""

    AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
    TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
    USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

    # Minimal required scopes for sharing posts and retrieving member identity
    DEFAULT_SCOPES = ["w_member_social", "openid", "profile", "email"]

    def __init__(self, cfg: Optional[Config] = None, db: Optional[Database] = None) -> None:
        self.config = cfg or default_config
        self.db = db or Database(self.config.database_path)

    def generate_authorization_url(self, scopes: Optional[list[str]] = None) -> tuple[str, str]:
        """Generate LinkedIn OAuth authorization URL with CSRF protection.
        
        Returns:
            (authorization_url, state)
        """
        missing = self.config.validate_oauth_credentials()
        if missing:
            raise OAuthError(
                f"Missing required LinkedIn credentials in configuration: {', '.join(missing)}. "
                "Please configure them in your .env file."
            )

        # Generate a cryptographically secure 32-byte URL-safe state
        state = secrets.token_urlsafe(32)
        # Store state in database with 10-minute TTL
        self.db.save_oauth_state(state=state, ttl_seconds=600)

        requested_scopes = scopes or self.DEFAULT_SCOPES
        params = {
            "response_type": "code",
            "client_id": self.config.linkedin_client_id,
            "redirect_uri": self.config.linkedin_redirect_uri,
            "state": state,
            "scope": " ".join(requested_scopes),
        }
        auth_url = f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"
        logger.info(f"Generated OAuth authorization URL for client {redact_secret(self.config.linkedin_client_id)}")
        return auth_url, state

    def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for an OAuth access token.
        
        Args:
            code: The authorization code received at the callback endpoint.
            
        Returns:
            Dict containing access_token, expires_in, and scope.
        """
        if not code:
            raise TokenExchangeError("Authorization code cannot be empty.")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.linkedin_redirect_uri,
            "client_id": self.config.linkedin_client_id,
            "client_secret": self.config.linkedin_client_secret,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, headers=headers, timeout=15)
        except requests.RequestException as e:
            raise TokenExchangeError(f"Network error while connecting to LinkedIn Token API: {e}") from e

        if response.status_code != 200:
            error_data = {}
            try:
                error_data = response.json()
            except Exception:
                pass
            err_desc = error_data.get("error_description", response.text)
            err_code = error_data.get("error", f"HTTP_{response.status_code}")
            logger.error(f"Token exchange failed: {err_code} - {err_desc}")
            raise TokenExchangeError(f"LinkedIn token exchange failed [{err_code}]: {err_desc}")

        token_payload = response.json()
        if "access_token" not in token_payload:
            raise TokenExchangeError("Malformed response from LinkedIn: missing 'access_token'.")

        logger.info(
            f"Successfully obtained access token (expires in {token_payload.get('expires_in', 0)} seconds)."
        )
        return token_payload

    def get_member_identity(self, access_token: str) -> dict[str, Any]:
        """Retrieve the authenticated member's OpenID Connect profile.
        
        Uses GET https://api.linkedin.com/v2/userinfo
        Returns:
            Dict with 'sub' (person identifier), 'name', 'email', etc.
        """
        if not access_token:
            raise UserinfoError("Access token is required to fetch member identity.")

        headers = {
            "Authorization": f"Bearer {access_token}",
        }

        try:
            response = requests.get(self.USERINFO_URL, headers=headers, timeout=10)
        except requests.RequestException as e:
            raise UserinfoError(f"Network error connecting to LinkedIn Userinfo API: {e}") from e

        if response.status_code != 200:
            logger.error(f"Userinfo request failed with status {response.status_code}: {response.text}")
            raise UserinfoError(
                f"Failed to fetch LinkedIn member identity [{response.status_code}]: {response.text}"
            )

        identity = response.json()
        sub = identity.get("sub")
        if not sub:
            raise UserinfoError("LinkedIn Userinfo response did not include 'sub' identifier.")

        logger.info(f"Retrieved identity for member: {identity.get('name', 'Unknown')} (sub: {sub})")
        return identity

    def process_callback(
        self,
        code: Optional[str] = None,
        state: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Validate OAuth callback parameters, exchange token, and store identity.
        
        Handles:
        - User denial (`error=access_denied`)
        - CSRF state validation and consumption
        - Token exchange
        - Member identity lookup
        - Persistence to database
        """
        # 1. Check for authorization denial or errors from LinkedIn
        if error:
            desc = error_description or "User or LinkedIn denied authorization."
            logger.warning(f"OAuth callback received error: {error} - {desc}")
            if error == "access_denied" or "user_cancelled" in desc.lower():
                raise AuthorizationDeniedError(f"Authorization denied by user: {desc}")
            raise OAuthError(f"OAuth error from LinkedIn [{error}]: {desc}")

        # 2. Validate state parameter
        if not state:
            raise StateValidationError("Missing state parameter in callback.")

        is_valid, reason = self.db.validate_and_consume_state(state)
        if not is_valid:
            logger.warning(f"OAuth state validation failed: {reason}")
            raise StateValidationError(f"Invalid OAuth state: {reason}")

        # 3. Verify code presence
        if not code:
            raise TokenExchangeError("Missing authorization code in callback.")

        # 4. Exchange code for access token
        token_data = self.exchange_code_for_token(code)
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days
        scope = token_data.get("scope", "")

        # 5. Fetch member identity (OpenID userinfo)
        identity = self.get_member_identity(access_token)
        member_id = identity.get("sub", "")
        member_name = identity.get("name", "")
        member_email = identity.get("email", "")

        # 6. Save token and member identity in database
        self.db.save_token(
            access_token=access_token,
            expires_in=expires_in,
            scope=scope,
            member_id=member_id,
            member_name=member_name,
            member_email=member_email,
        )

        return {
            "status": "success",
            "member_id": member_id,
            "member_urn": f"urn:li:person:{member_id}",
            "member_name": member_name,
            "member_email": member_email,
            "expires_in": expires_in,
            "scope": scope,
        }
