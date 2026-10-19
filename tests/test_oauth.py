"""Tests for LinkedIn OAuth 2.0 flow and OpenID identity retrieval."""

import os
import tempfile
import urllib.parse
from unittest.mock import MagicMock, patch
import pytest

from src.config import Config
from src.db import Database
from src.oauth import (
    AuthorizationDeniedError,
    LinkedInOAuth,
    OAuthError,
    StateValidationError,
    TokenExchangeError,
    UserinfoError,
)


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_oauth.db"
    return Database(db_path)


@pytest.fixture
def test_config():
    cfg = Config()
    cfg.linkedin_client_id = "test_client_id_123"
    cfg.linkedin_client_secret = "test_client_secret_xyz"
    cfg.linkedin_redirect_uri = "http://localhost:8000/auth/linkedin/callback"
    return cfg


def test_generate_authorization_url_success(temp_db, test_config):
    """Test generating a properly constructed OAuth URL with CSRF state."""
    oauth = LinkedInOAuth(test_config, temp_db)
    url, state = oauth.generate_authorization_url()

    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.linkedin.com"
    assert parsed.path == "/oauth/v2/authorization"

    params = urllib.parse.parse_qs(parsed.query)
    assert params["response_type"] == ["code"]
    assert params["client_id"] == [test_config.linkedin_client_id]
    assert params["redirect_uri"] == [test_config.linkedin_redirect_uri]
    assert params["state"] == [state]
    assert "w_member_social" in params["scope"][0]
    assert "openid" in params["scope"][0]

    # Verify state was saved in DB
    is_valid, _ = temp_db.validate_and_consume_state(state)
    assert is_valid is True


def test_generate_authorization_url_missing_credentials(temp_db):
    """Test that missing client ID/secret raises clear OAuthError."""
    cfg = Config()
    cfg.linkedin_client_id = ""
    cfg.linkedin_client_secret = ""

    oauth = LinkedInOAuth(cfg, temp_db)
    with pytest.raises(OAuthError, match="Missing required LinkedIn credentials"):
        oauth.generate_authorization_url()


def test_token_exchange_success(temp_db, test_config):
    """Test exchanging authorization code for token with mocked LinkedIn response."""
    oauth = LinkedInOAuth(test_config, temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "mocked_access_token_12345",
        "expires_in": 5184000,
        "scope": "w_member_social openid profile email",
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        token_data = oauth.exchange_code_for_token("auth_code_abc")
        assert token_data["access_token"] == "mocked_access_token_12345"
        assert token_data["expires_in"] == 5184000

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["data"]["code"] == "auth_code_abc"
        assert call_kwargs["data"]["client_id"] == "test_client_id_123"


def test_token_exchange_http_error(temp_db, test_config):
    """Test token exchange when LinkedIn returns HTTP 400."""
    oauth = LinkedInOAuth(test_config, temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "Invalid authorization code"
    mock_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "The provided authorization code is invalid or expired",
    }

    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(TokenExchangeError, match="invalid_grant.*invalid or expired"):
            oauth.exchange_code_for_token("invalid_code")


def test_get_member_identity_success(temp_db, test_config):
    """Test fetching OpenID member identity with 'sub' identifier."""
    oauth = LinkedInOAuth(test_config, temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "sub": "abc123xyz",
        "name": "Alex Smith",
        "given_name": "Alex",
        "family_name": "Smith",
        "email": "alex@example.com",
    }

    with patch("requests.get", return_value=mock_resp):
        identity = oauth.get_member_identity("valid_token")
        assert identity["sub"] == "abc123xyz"
        assert identity["name"] == "Alex Smith"
        assert identity["email"] == "alex@example.com"


def test_get_member_identity_missing_sub(temp_db, test_config):
    """Test error handling when userinfo response is missing 'sub'."""
    oauth = LinkedInOAuth(test_config, temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"name": "No Sub Member"}

    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(UserinfoError, match="did not include 'sub'"):
            oauth.get_member_identity("valid_token")


def test_callback_user_denial(temp_db, test_config):
    """Test that authorization denial by user is caught gracefully."""
    oauth = LinkedInOAuth(test_config, temp_db)
    with pytest.raises(AuthorizationDeniedError, match="Authorization denied by user"):
        oauth.process_callback(
            error="access_denied",
            error_description="The user denied your application access",
        )


def test_callback_invalid_state(temp_db, test_config):
    """Test that forged or missing state raises StateValidationError."""
    oauth = LinkedInOAuth(test_config, temp_db)

    # Missing state
    with pytest.raises(StateValidationError, match="Missing state"):
        oauth.process_callback(code="auth_code_123", state=None)

    # Unknown state
    with pytest.raises(StateValidationError, match="Unknown or forged"):
        oauth.process_callback(code="auth_code_123", state="forged_state")


def test_callback_full_success_flow(temp_db, test_config):
    """Test complete callback flow: state consumed, token stored, identity saved."""
    oauth = LinkedInOAuth(test_config, temp_db)

    # Generate state and store in temp_db
    _, valid_state = oauth.generate_authorization_url()

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "returned_access_token_999",
        "expires_in": 5184000,
        "scope": "w_member_social openid profile email",
    }

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "sub": "person_sub_888",
        "name": "Taylor Developer",
        "email": "taylor@example.com",
    }

    with patch("requests.post", return_value=mock_token_resp):
        with patch("requests.get", return_value=mock_userinfo_resp):
            result = oauth.process_callback(code="good_code_123", state=valid_state)

            assert result["status"] == "success"
            assert result["member_id"] == "person_sub_888"
            assert result["member_urn"] == "urn:li:person:person_sub_888"
            assert result["member_name"] == "Taylor Developer"

            # Verify saved in DB
            saved_token = temp_db.get_token()
            assert saved_token is not None
            assert saved_token["access_token"] == "returned_access_token_999"
            assert saved_token["member_id"] == "person_sub_888"
