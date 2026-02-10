"""DeviantArt session handling.

Authenticates using browser cookies. On first use, loads the notes page
to extract the CSRF token and folder list from the embedded initial state.
"""

import json
import re
import sys

import requests

NOTES_PAGE = "https://www.deviantart.com/messages/notes"
DA_MINOR_VERSION = "20230710"


class DASession:
    """Manages cookies, CSRF token, and folder metadata for the DA notes API."""

    def __init__(self, cookie_string, user_agent=None):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/144.0.0.0 Safari/537.36"
        )
        self.session.headers["Accept"] = "application/json, text/plain, */*"
        self.session.headers["Referer"] = NOTES_PAGE

        # Load cookies from the raw cookie string
        for pair in cookie_string.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                self.session.cookies.set(name.strip(), value.strip())

        self.csrf_token = None
        self.folders = []

    def init(self):
        """Load the notes page to extract CSRF token and folder list."""
        print("Loading notes page to extract session data...")
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
            total = sum(f.get("count", 0) for f in self.folders)
            print(f"  {len(self.folders)} folder(s), {total} total note(s).")
        print()
