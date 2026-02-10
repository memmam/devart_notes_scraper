"""DeviantArt Notes API client.

Uses the internal /_puppy/notes/ endpoints with cookie auth + CSRF token.
"""

import sys
import time

import requests

from auth import DA_MINOR_VERSION

API_BASE = "https://www.deviantart.com/_puppy/notes"
MAX_RETRIES = 4
RETRY_BACKOFF = [2, 4, 8, 16]


class DANotesClient:
    """Wraps the DA internal notes API with pagination support."""

    def __init__(self, da_session, request_delay=1.0):
        self.da = da_session
        self.delay = request_delay

    def _get(self, path, params=None):
        if self.delay > 0:
            time.sleep(self.delay)

        if params is None:
            params = {}
        params["da_minor_version"] = DA_MINOR_VERSION
        params["csrf_token"] = self.da.csrf_token

        url = f"{API_BASE}{path}"

        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.da.session.get(url, params=params, timeout=30)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF[attempt]
                    print(f"\n    Connection error, retrying in {wait}s... ({exc.__class__.__name__})", flush=True)
                    time.sleep(wait)
                else:
                    raise

        if resp.status_code == 400:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if body.get("errorDetails", {}).get("csrf"):
                print(
                    "Error: CSRF token rejected. Your session may have expired.\n"
                    "Refresh the notes page in your browser and update your cookies/CSRF.",
                    file=sys.stderr,
                )
                sys.exit(1)

        if resp.status_code == 401:
            print(
                "Error: 401 Unauthorized. Your cookies may be expired.\n"
                "Log into DeviantArt in your browser and grab fresh cookies.",
                file=sys.stderr,
            )
            sys.exit(1)

        resp.raise_for_status()
        return resp.json()

    # -- notes listing with pagination --

    def get_notes_page(self, folder_id, offset=0, limit=24):
        """Fetch a single page of notes from a folder."""
        return self._get("/list", params={
            "folderid": folder_id,
            "offset": offset,
            "limit": limit,
        })

    def iter_notes(self, folder_id, limit=24):
        """Yield every note in a folder, handling pagination automatically."""
        offset = 0
        while True:
            page = self.get_notes_page(folder_id, offset=offset, limit=limit)
            results = page.get("results", [])
            for note in results:
                yield note
            if not page.get("hasMore"):
                break
            offset = page.get("nextOffset", offset + len(results))
