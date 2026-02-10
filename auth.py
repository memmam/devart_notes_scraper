"""DeviantArt OAuth2 authentication."""

import json
import os
import sys
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs

import requests

AUTH_URL = "https://www.deviantart.com/oauth2/authorize"
TOKEN_URL = "https://www.deviantart.com/oauth2/token"
TOKEN_CACHE = ".da_token.json"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth2 redirect callback."""

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            self.server.auth_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authorization successful.</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        else:
            self.server.auth_code = None
            error = query.get("error", ["unknown"])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"<html><body><h1>Authorization failed: {error}</h1></body></html>".encode()
            )

    def log_message(self, format, *args):
        pass  # suppress default logging


def _load_cached_token():
    """Load a previously cached token if it exists and is still valid."""
    if not os.path.exists(TOKEN_CACHE):
        return None
    with open(TOKEN_CACHE) as f:
        data = json.load(f)
    if data.get("expires_at", 0) > time.time() + 60:
        return data
    # expired — try to refresh
    if data.get("refresh_token"):
        return _refresh(data)
    return None


def _save_token(data):
    with open(TOKEN_CACHE, "w") as f:
        json.dump(data, f, indent=2)


def _refresh(token_data):
    """Attempt to refresh an expired token."""
    # We need client creds to refresh — load them from config if available
    config_path = os.environ.get("DA_CONFIG", "config.json")
    if not os.path.exists(config_path):
        return None
    with open(config_path) as f:
        cfg = json.load(f)
    if not cfg.get("client_id") or not cfg.get("client_secret"):
        return None

    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": token_data["refresh_token"],
    })
    if resp.status_code != 200:
        return None
    new = resp.json()
    new["expires_at"] = time.time() + new.get("expires_in", 3600)
    _save_token(new)
    return new


def _run_oauth_flow(client_id, client_secret, port=8080):
    """Run the full Authorization Code flow with a local callback server."""
    redirect_uri = f"http://localhost:{port}/callback"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "browse message",
    }
    url = f"{AUTH_URL}?{urlencode(params)}"

    print(f"Opening browser for DeviantArt authorization...")
    print(f"If it doesn't open automatically, visit:\n  {url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.auth_code = None
    server.timeout = 120
    server.handle_request()

    if not server.auth_code:
        print("Error: No authorization code received.", file=sys.stderr)
        sys.exit(1)

    # Exchange code for token
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": server.auth_code,
        "redirect_uri": redirect_uri,
    })
    if resp.status_code != 200:
        print(f"Error exchanging code for token: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    _save_token(data)
    print("Authorization successful. Token cached.\n")
    return data


def get_access_token(config):
    """Resolve a valid access token from config or cached credentials.

    Supports two auth methods:
      1. Direct access_token in config (e.g. grabbed from browser devtools)
      2. OAuth2 client_id + client_secret (runs browser-based Authorization Code flow)
    """
    # Method 1: direct token
    if config.get("access_token"):
        return config["access_token"]

    # Method 2: try cached token first
    cached = _load_cached_token()
    if cached:
        return cached["access_token"]

    # Method 2: need to run OAuth flow
    cid = config.get("client_id")
    csec = config.get("client_secret")
    if not cid or not csec:
        print(
            "Error: No credentials configured.\n"
            "Provide either:\n"
            "  - 'access_token' (grab from browser devtools), or\n"
            "  - 'client_id' + 'client_secret' (register at https://www.deviantart.com/developers/apps)\n"
            "in your config.json file.",
            file=sys.stderr,
        )
        sys.exit(1)

    port = config.get("callback_port", 8080)
    data = _run_oauth_flow(cid, csec, port=port)
    return data["access_token"]
