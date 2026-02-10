"""DeviantArt session handling.

Authenticates using browser cookies. On first use, loads the notes page
to extract the CSRF token and folder list from the embedded initial state.

If credentials are available (config or interactive prompt), can re-login
automatically when cookies expire during a long scrape.
"""

import getpass
import json
import re
import sys

import requests

NOTES_PAGE = "https://www.deviantart.com/messages/notes"
LOGIN_PAGE = "https://www.deviantart.com/users/login"
LOGIN_POST = "https://www.deviantart.com/_sisu/do/signin"
DA_MINOR_VERSION = "20230710"


class DASession:
    """Manages cookies, CSRF token, and folder metadata for the DA notes API."""

    def __init__(self, cookie_string=None, username=None, password=None, user_agent=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/144.0.0.0 Safari/537.36"
        )
        self.session.headers["Accept"] = "application/json, text/plain, */*"
        self.session.headers["Referer"] = NOTES_PAGE

        self.username = username
        self.password = password
        self.csrf_token = None
        self.folders = []

        if cookie_string:
            for pair in cookie_string.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    self.session.cookies.set(name.strip(), value.strip())

    def login(self):
        """Log into DeviantArt with username/password to obtain session cookies."""
        username = self.username
        password = self.password

        if not username:
            username = input("DeviantArt username: ")
        if not password:
            password = getpass.getpass("DeviantArt password: ")

        print("Logging into DeviantArt...", flush=True)

        # Fetch the login page to get hidden form fields (CSRF etc.)
        resp = self.session.get(LOGIN_PAGE)
        if resp.status_code != 200:
            print(f"Error: Could not load login page (HTTP {resp.status_code}).", file=sys.stderr)
            return False

        # Extract hidden input fields
        data = {}
        for m in re.finditer(
            r'<input\s+type="hidden"\s+name="([^"]+)"\s+value="([^"]*)"', resp.text
        ):
            data[m.group(1)] = m.group(2)

        data["username"] = username
        data["password"] = password
        data["remember"] = "on"

        if data.get("challenge") and data["challenge"] != "0":
            print(
                "Error: DeviantArt is requesting a CAPTCHA challenge.\n"
                "Log in via your browser and use cookies.txt instead.",
                file=sys.stderr,
            )
            return False

        resp = self.session.post(LOGIN_POST, data=data, allow_redirects=True)

        # Success = server redirected after login
        if not resp.history:
            print("Error: Login failed — check your username and password.", file=sys.stderr)
            return False

        # Verify we got the auth cookies
        cookie_names = {c.name for c in self.session.cookies}
        if "auth" not in cookie_names or "auth_secure" not in cookie_names:
            print("Error: Login succeeded but auth cookies not set.", file=sys.stderr)
            return False

        print("  Login successful.", flush=True)
        return True

    def relogin(self):
        """Attempt to re-login. Returns True on success."""
        if not self.username and not self.password:
            # No credentials stored — prompt interactively
            print("\nSession expired. Re-login required.", flush=True)
        else:
            print("\n    Session expired, re-logging in...", flush=True)

        if not self.login():
            return False

        # Refresh CSRF token after re-login
        return self._extract_csrf()

    def _extract_csrf(self):
        """Fetch the notes page and extract CSRF token + folders."""
        resp = self.session.get(NOTES_PAGE)
        if resp.status_code != 200:
            return False

        html = resp.text

        m = re.search(r"window\.__CSRF_TOKEN__\s*=\s*'([^']+)'", html)
        if not m:
            return False
        self.csrf_token = m.group(1)

        m = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*JSON\.parse\(\"(.*?)\"\);", html
        )
        if m:
            raw = m.group(1).replace("\\'", "'")
            try:
                inner = json.loads('"' + raw + '"')
                state = json.loads(inner)
                self.folders = state.get("notes", {}).get("folders", [])
            except (json.JSONDecodeError, KeyError):
                pass

        print(f"  CSRF token acquired.", flush=True)
        return True

    def init(self):
        """Load the notes page to extract CSRF token and folder list."""
        print("Loading notes page to extract session data...", flush=True)
        resp = self.session.get(NOTES_PAGE)
        if resp.status_code != 200:
            print(
                f"Error: Failed to load notes page (HTTP {resp.status_code}).\n"
                "Your cookies may be expired — grab fresh ones from your browser.",
                file=sys.stderr,
            )
            sys.exit(1)

        html = resp.text

        # Extract CSRF token
        m = re.search(r"window\.__CSRF_TOKEN__\s*=\s*'([^']+)'", html)
        if not m:
            print("Error: Could not find CSRF token in page.", file=sys.stderr)
            sys.exit(1)
        self.csrf_token = m.group(1)

        # Extract initial state for folder list
        m = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*JSON\.parse\(\"(.*?)\"\);", html
        )
        if m:
            raw = m.group(1).replace("\\'", "'")
            try:
                inner = json.loads('"' + raw + '"')
                state = json.loads(inner)
                self.folders = state.get("notes", {}).get("folders", [])
            except (json.JSONDecodeError, KeyError):
                pass  # folders will be discovered via fallback

        if not self.folders:
            print("Warning: Could not parse folder list from page.", file=sys.stderr)

        print(f"  CSRF token acquired.")
        if self.folders:
            real = [f for f in self.folders if f.get("folderId", 0) >= 0]
            total = sum(f.get("count", 0) for f in real)
            print(f"  {len(real)} folder(s), {total} total note(s).")
        print()
