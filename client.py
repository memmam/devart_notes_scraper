"""DeviantArt Notes API client."""

import sys
import time

import requests

API_BASE = "https://www.deviantart.com/api/v1/oauth2"


class DANotesClient:
    """Thin wrapper around the DeviantArt OAuth2 notes endpoints."""

    def __init__(self, access_token, request_delay=1.0):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"
        self.delay = request_delay

    def _get(self, path, params=None):
        time.sleep(self.delay)
        url = f"{API_BASE}{path}"
        resp = self.session.get(url, params=params)
        if resp.status_code == 401:
            print(
                "Error: 401 Unauthorized. Your access token may be expired or invalid.",
                file=sys.stderr,
            )
            sys.exit(1)
        resp.raise_for_status()
        return resp.json()

    # -- folders --

    def get_folders(self):
        """Return the list of note folders."""
        return self._get("/notes/folders")

    # -- notes listing --

    def get_notes_page(self, folder_id=None, offset=0, limit=25):
        """Fetch a single page of notes from a folder."""
        params = {"offset": offset, "limit": limit}
        if folder_id is not None:
            params["folderid"] = folder_id
        return self._get("/notes", params=params)

    def iter_notes(self, folder_id=None, limit=25):
        """Yield every note summary in a folder, handling pagination."""
        offset = 0
        while True:
            page = self.get_notes_page(folder_id=folder_id, offset=offset, limit=limit)
            for note in page.get("results", []):
                yield note
            if not page.get("has_more"):
                break
            offset = page.get("next_offset", offset + limit)

    # -- single note --

    def get_note(self, note_id):
        """Fetch the full content of a single note."""
        return self._get(f"/notes/{note_id}")
