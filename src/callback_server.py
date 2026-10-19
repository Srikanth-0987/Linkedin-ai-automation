"""Local HTTP server to handle LinkedIn OAuth callback on localhost:8000.

Provides immediate browser feedback upon successful authentication or denial.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import urllib.parse
from typing import Optional
from loguru import logger

from src.oauth import LinkedInOAuth, OAuthError


class CallbackHandler(BaseHTTPRequestHandler):
    """Handles incoming requests for /auth/linkedin/callback."""

    oauth_service: LinkedInOAuth
    server_instance: HTTPServer
    auth_result: Optional[dict] = None
    auth_error: Optional[Exception] = None

    def log_message(self, format: str, *args) -> None:
        # Route standard HTTP server logs to loguru
        logger.debug(f"HTTP {self.command}: {format % args}")

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path != "/auth/linkedin/callback":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found. Please visit /auth/linkedin/callback")
            return

        query_params = urllib.parse.parse_qs(parsed_url.query)
        code = query_params.get("code", [None])[0]
        state = query_params.get("state", [None])[0]
        error = query_params.get("error", [None])[0]
        error_description = query_params.get("error_description", [None])[0]

        try:
            result = self.oauth_service.process_callback(
                code=code,
                state=state,
                error=error,
                error_description=error_description,
            )
            CallbackHandler.auth_result = result
            self.render_success(result)
        except Exception as e:
            CallbackHandler.auth_error = e
            self.render_error(str(e))

        # Schedule server shutdown after serving response
        threading.Thread(target=self.server_instance.shutdown).start()

    def render_success(self, result: dict) -> None:
        name = html.escape(result.get("member_name", "LinkedIn Member"))
        sub = html.escape(result.get("member_id", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LinkedIn Connected</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border-radius: 12px;
            padding: 32px;
            max-width: 480px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            text-align: center;
            border: 1px solid #334155;
        }}
        .badge {{
            background: #059669;
            color: white;
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            display: inline-block;
            margin-bottom: 16px;
        }}
        h1 {{ margin: 0 0 12px; font-size: 24px; }}
        p {{ color: #94a3b8; font-size: 15px; line-height: 1.6; margin: 0 0 20px; }}
        .details {{
            background: #0f172a;
            border-radius: 8px;
            padding: 12px;
            font-family: monospace;
            font-size: 13px;
            color: #38bdf8;
            margin-bottom: 20px;
            text-align: left;
        }}
        .tip {{ font-size: 13px; color: #64748b; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">Connected</div>
        <h1>LinkedIn Account Linked!</h1>
        <p>Authenticated successfully as <strong>{name}</strong>.</p>
        <div class="details">
            Member ID: {sub}<br>
            Status: Token Stored Securely<br>
            Scopes: w_member_social, openid, profile
        </div>
        <p class="tip">You can now close this tab and return to your terminal.</p>
    </div>
</body>
</html>"""
        self.wfile.write(html_content.encode("utf-8"))

    def render_error(self, message: str) -> None:
        safe_msg = html.escape(message)
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LinkedIn Auth Error</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border-radius: 12px;
            padding: 32px;
            max-width: 480px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
            text-align: center;
            border: 1px solid #dc2626;
        }}
        .badge {{
            background: #dc2626;
            color: white;
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            display: inline-block;
            margin-bottom: 16px;
        }}
        h1 {{ margin: 0 0 12px; font-size: 22px; }}
        p {{ color: #94a3b8; font-size: 14px; line-height: 1.5; margin: 0 0 20px; }}
        .error-box {{
            background: #0f172a;
            border-radius: 8px;
            padding: 12px;
            color: #f87171;
            font-size: 13px;
            margin-bottom: 20px;
            text-align: left;
            word-break: break-word;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="badge">Auth Failed</div>
        <h1>Connection Unsuccessful</h1>
        <div class="error-box">{safe_msg}</div>
        <p>Please check your LinkedIn app configuration or retry the login command.</p>
    </div>
</body>
</html>"""
        self.wfile.write(html_content.encode("utf-8"))


def start_callback_server(oauth_service: LinkedInOAuth, port: int = 8000, timeout_seconds: int = 180) -> dict:
    """Start localhost callback server and wait for LinkedIn redirect.
    
    Args:
        oauth_service: Initialized LinkedInOAuth instance.
        port: Port number (must match registered redirect URI port: 8000).
        timeout_seconds: Maximum time to wait for user to authenticate in browser.
        
    Returns:
        Result dictionary containing member_id, member_name, etc.
    """
    server = HTTPServer(("localhost", port), CallbackHandler)
    CallbackHandler.oauth_service = oauth_service
    CallbackHandler.server_instance = server
    CallbackHandler.auth_result = None
    CallbackHandler.auth_error = None

    logger.info(f"Local OAuth callback server listening on http://localhost:{port}/auth/linkedin/callback")

    timer = threading.Timer(timeout_seconds, server.shutdown)
    timer.start()

    try:
        server.serve_forever()
    finally:
        timer.cancel()
        server.server_close()

    if CallbackHandler.auth_error:
        raise CallbackHandler.auth_error

    if not CallbackHandler.auth_result:
        raise OAuthError("OAuth authentication timed out before receiving callback.")

    return CallbackHandler.auth_result
