"""Tests for the local OAuth HTTP callback handler."""

import io
from unittest.mock import MagicMock
import pytest

from src.callback_server import CallbackHandler


class DummyServer:
    def shutdown(self):
        pass


def test_callback_handler_404():
    """Verify that visiting non-callback paths returns 404."""
    handler = CallbackHandler.__new__(CallbackHandler)
    handler.path = "/unknown/path"
    handler.command = "GET"
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.server_instance = DummyServer()

    # Mock send_response and send_header
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    handler.do_GET()

    handler.send_response.assert_called_with(404)
    output = handler.wfile.getvalue().decode()
    assert "404 Not Found" in output


def test_callback_handler_success():
    """Verify that visiting /auth/linkedin/callback with valid parameters returns 200 HTML."""
    handler = CallbackHandler.__new__(CallbackHandler)
    handler.path = "/auth/linkedin/callback?code=mock_code&state=mock_state"
    handler.command = "GET"
    handler.rfile = io.BytesIO()
    handler.wfile = io.BytesIO()
    handler.server_instance = DummyServer()

    mock_oauth = MagicMock()
    mock_oauth.process_callback.return_value = {
        "status": "success",
        "member_name": "Test User",
        "member_id": "sub_987",
        "scope": "w_member_social openid profile",
        "expires_in": 5184000,
    }
    CallbackHandler.oauth_service = mock_oauth

    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()

    handler.do_GET()

    handler.send_response.assert_called_with(200)
    output = handler.wfile.getvalue().decode()
    assert "LinkedIn Account Linked!" in output
    assert "Test User" in output
    assert "sub_987" in output
