#!/usr/bin/env python3
"""DeviantArt Legacy Notes Scraper.

Two execution modes:
  list    – Paginate through note folders and collect a URL for every note.
  extract – Download the full content of every note and save it locally.
  both    – Run list first, then extract (default).

Authentication uses browser cookies. See config.example.json.

Usage:
  python main.py --mode list
  python main.py --mode extract
  python main.py --mode both
  python main.py --mode list --folders 1 2
"""

import argparse
import json
import os
import sys

from auth import DASession
from client import DANotesClient

# Folders with negative IDs are virtual views (Unread, Starred, Drafts, Spam).
# They overlap with real folders, so skip them by default to avoid duplicates.
VIRTUAL_FOLDER_IDS = {-1, -2, -3, -4}


def load_config(path):
    if not os.path.exists(path):
        print(
            f"Config file not found: {path}\n"
            "Copy config.example.json to config.json and fill in your cookie string.",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def resolve_folders(da_session, requested_ids):
    """Return the list of folders to scrape.

    If specific IDs were requested, use those. Otherwise use all real
    (non-virtual) folders from the page's initial state.
    """
    all_folders = da_session.folders
    if requested_ids:
        by_id = {f["folderId"]: f for f in all_folders}
        folders = []
        for fid in requested_ids:
            if fid in by_id:
                folders.append(by_id[fid])
            else:
                folders.append({"folderId": fid, "title": f"Folder {fid}", "count": "?"})
        return folders

    return [f for f in all_folders if f["folderId"] not in VIRTUAL_FOLDER_IDS]


# ---------------------------------------------------------------------------
# Mode 1: list
# ---------------------------------------------------------------------------

def run_list(client, folders, output_dir):
    """Scrape every specified folder and write a URL manifest."""
    entries = []
    for folder in folders:
        fname = folder["title"]
        fid = folder["folderId"]
        fcount = folder.get("count", "?")
        print(f"  {fname} (id={fid}, ~{fcount} notes)")

        count = 0
        for note in client.iter_notes(folder_id=fid):
            entry = {
                "note_id": note["noteId"],
                "url": note.get("url", ""),
                "subject": note.get("subject", ""),
                "sender": note.get("sender", {}).get("username", ""),
                "timestamp": note.get("timestamp", ""),
                "folder": fname,
                "folder_id": fid,
            }
            entries.append(entry)
            count += 1
        print(f"    -> {count} note(s) collected")

    # Plain URL list
    urls_path = os.path.join(output_dir, "note_urls.txt")
    with open(urls_path, "w") as f:
        for e in entries:
            f.write(f"{e['url']}\n")

    # Detailed JSON manifest
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

def run_extract(client, folders, output_dir):
    """Download full note content and save each note as a JSON file."""
    notes_dir = os.path.join(output_dir, "notes")
    os.makedirs(notes_dir, exist_ok=True)

    saved = 0
    errors = 0

    for folder in folders:
        fname = folder["title"]
        fid = folder["folderId"]
        fcount = folder.get("count", "?")
        print(f"  {fname} (id={fid}, ~{fcount} notes)")

        count = 0
        for note in client.iter_notes(folder_id=fid):
            nid = note["noteId"]
            subj = note.get("subject", "(no subject)")
            count += 1
            try:
                path = os.path.join(notes_dir, f"{nid}.json")
                with open(path, "w") as f:
                    json.dump(note, f, indent=2, ensure_ascii=False)
                saved += 1
            except Exception as exc:
                print(f"    error saving {nid}: {exc}", file=sys.stderr)
                errors += 1
        print(f"    -> {count} note(s) saved")

    print(f"\nDone. {saved} saved, {errors} error(s).")
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
            "  python main.py --mode list --folders 1 2\n"
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
        "--folders",
        type=int,
        nargs="+",
        metavar="ID",
        help="only scrape these folder IDs (default: all real folders)",
    )

    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)

    # Load config and authenticate
    config = load_config(args.config)
    cookie_string = config.get("cookies", "")
    if not cookie_string:
        print(
            "Error: No cookie string in config.json.\n"
            "Open DevTools on deviantart.com, copy your cookie header value,\n"
            "and paste it as the \"cookies\" field in config.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    da = DASession(cookie_string)
    da.init()

    client = DANotesClient(da, request_delay=args.delay)
    folders = resolve_folders(da, args.folders)

    if not folders:
        print("No folders to scrape.", file=sys.stderr)
        sys.exit(1)

    print(f"Scraping {len(folders)} folder(s)...\n")

    if args.mode in ("list", "both"):
        run_list(client, folders, args.output)

    if args.mode in ("extract", "both"):
        run_extract(client, folders, args.output)


if __name__ == "__main__":
    main()
