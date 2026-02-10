#!/usr/bin/env python3
"""DeviantArt Legacy Notes Scraper.

Two execution modes:
  list    – Paginate through every note folder and collect a URL/ID for each note.
  extract – Download the full content of each note and save it locally as JSON.
  both    – Run list first, then extract (default).

Usage:
  python main.py --mode list
  python main.py --mode extract
  python main.py --mode both
  python main.py --mode extract --from-list output/note_urls.json
"""

import argparse
import json
import os
import sys

from auth import get_access_token
from client import DANotesClient

NOTES_WEB_BASE = "https://www.deviantart.com/notifications/notes"


def load_config(path):
    if not os.path.exists(path):
        print(
            f"Config file not found: {path}\n"
            "Copy config.example.json to config.json and fill in your credentials.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Mode 1: list
# ---------------------------------------------------------------------------

def run_list(client, output_dir):
    """Scrape every note folder and write a URL manifest."""
    print("Fetching note folders...")
    folders_resp = client.get_folders()
    folders = folders_resp.get("results", [])
    print(f"  Found {len(folders)} folder(s).\n")

    entries = []
    for folder in folders:
        fname = folder.get("title", "Unknown")
        fid = folder.get("folderid")
        count = 0
        for note in client.iter_notes(folder_id=fid):
            nid = note.get("noteid")
            entry = {
                "note_id": nid,
                "url": f"{NOTES_WEB_BASE}/#view={nid}",
                "subject": note.get("subject", ""),
                "sender": note.get("user", {}).get("username", ""),
                "ts": note.get("ts"),
                "folder": fname,
                "unread": note.get("unread", False),
            }
            entries.append(entry)
            count += 1
        print(f"  {fname}: {count} note(s)")

    # Write plain URL list (one per line)
    urls_path = os.path.join(output_dir, "note_urls.txt")
    with open(urls_path, "w") as f:
        for e in entries:
            f.write(f"{e['url']}\n")

    # Write detailed JSON manifest
    json_path = os.path.join(output_dir, "note_urls.json")
    with open(json_path, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"\n{len(entries)} note URL(s) total.")
    print(f"  URLs  -> {urls_path}")
    print(f"  JSON  -> {json_path}")
    return entries


# ---------------------------------------------------------------------------
# Mode 2: extract
# ---------------------------------------------------------------------------

def run_extract(client, output_dir, note_list=None):
    """Download full note content and save each note as a JSON file."""
    notes_dir = os.path.join(output_dir, "notes")
    os.makedirs(notes_dir, exist_ok=True)

    # If no pre-built list, discover notes now
    if note_list is None:
        print("No URL list supplied — discovering notes first...\n")
        note_list = []
        folders_resp = client.get_folders()
        for folder in folders_resp.get("results", []):
            for note in client.iter_notes(folder_id=folder.get("folderid")):
                note_list.append({
                    "note_id": note.get("noteid"),
                    "folder": folder.get("title", "Unknown"),
                })

    total = len(note_list)
    if total == 0:
        print("Nothing to extract.")
        return

    print(f"Extracting {total} note(s)...\n")
    errors = 0
    for i, entry in enumerate(note_list, 1):
        nid = entry["note_id"]
        label = entry.get("subject") or entry.get("folder") or str(nid)
        print(f"  [{i}/{total}] {nid} ({label})")
        try:
            data = client.get_note(nid)
            path = os.path.join(notes_dir, f"{nid}.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"    -> error: {exc}", file=sys.stderr)
            errors += 1

    print(f"\nDone. {total - errors} saved, {errors} error(s).")
    print(f"  Notes -> {notes_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape DeviantArt legacy notes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python main.py --mode list\n"
            "  python main.py --mode extract\n"
            "  python main.py --mode both\n"
            "  python main.py --mode extract --from-list output/note_urls.json\n"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["list", "extract", "both"],
        default="both",
        help="list = collect URLs, extract = download content, both = both (default: both)",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="path to config file (default: config.json)",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="output directory (default: output)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds between API requests (default: 1.0)",
    )
    parser.add_argument(
        "--from-list",
        metavar="JSON_FILE",
        help="extract notes listed in a previously generated note_urls.json",
    )

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)

    # Authenticate
    config = load_config(args.config)
    token = get_access_token(config)
    client = DANotesClient(token, request_delay=args.delay)

    # Dispatch
    note_list = None

    if args.mode in ("list", "both"):
        note_list = run_list(client, args.output)

    if args.mode in ("extract", "both"):
        if args.from_list:
            with open(args.from_list) as f:
                note_list = json.load(f)
        run_extract(client, args.output, note_list=note_list)


if __name__ == "__main__":
    main()
