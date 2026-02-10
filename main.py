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
    urls_path = os.path.join(output_dir, "note_urls.txt")
    json_path = os.path.join(output_dir, "note_urls.json")

    for folder in folders:
        fname = folder["title"]
        fid = folder["folderId"]
        fcount = folder.get("count", "?")

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
            print(f"\r    {fname}: {count}/{fcount} notes", end="", flush=True)
        print(f"\r    {fname}: {count} note(s) collected" + " " * 20)

    # Write files
    with open(urls_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(f"{e['url']}\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"\n{len(entries)} note URL(s) total.")
    print(f"  URLs  -> {urls_path}")
    print(f"  JSON  -> {json_path}")
    return entries


# ---------------------------------------------------------------------------
# Mode: both (single pass — list + extract in one pagination sweep)
# ---------------------------------------------------------------------------

def _load_progress(output_dir):
    """Load saved pagination offsets from a previous interrupted run."""
    path = os.path.join(output_dir, ".progress.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_progress(output_dir, progress):
    """Save pagination offsets so we can resume later."""
    path = os.path.join(output_dir, ".progress.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(progress, f)


def run_both(client, folders, output_dir):
    """Paginate once, writing URL manifest and per-note JSON simultaneously."""
    notes_dir = os.path.join(output_dir, "notes")
    os.makedirs(notes_dir, exist_ok=True)
    urls_path = os.path.join(output_dir, "note_urls.txt")
    json_path = os.path.join(output_dir, "note_urls.json")

    progress = _load_progress(output_dir)
    entries = []
    saved = 0
    skipped = 0
    errors = 0

    for folder in folders:
        fname = folder["title"]
        fid = folder["folderId"]
        fcount = folder.get("count", "?")
        start_offset = progress.get(str(fid), 0)

        if start_offset == "done":
            print(f"  {fname}: already complete, skipping")
            continue

        if start_offset > 0:
            print(f"  {fname}: resuming from offset {start_offset}")

        count = start_offset
        for note in client.iter_notes(folder_id=fid, start_offset=start_offset):
            nid = note["noteId"]
            count += 1

            # Collect URL entry
            entries.append({
                "note_id": nid,
                "url": note.get("url", ""),
                "subject": note.get("subject", ""),
                "sender": note.get("sender", {}).get("username", ""),
                "timestamp": note.get("timestamp", ""),
                "folder": fname,
                "folder_id": fid,
            })

            # Skip notes already on disk
            note_path = os.path.join(notes_dir, f"{nid}.json")
            if os.path.exists(note_path):
                skipped += 1
                print(f"\r    {fname}: {count}/{fcount} (skipped existing)", end="", flush=True)
                # Still save progress so we don't re-paginate these
                progress[str(fid)] = count
                _save_progress(output_dir, progress)
                continue

            # Write note to disk immediately
            try:
                with open(note_path, "w", encoding="utf-8") as f:
                    json.dump(note, f, indent=2, ensure_ascii=False)
                saved += 1
            except Exception as exc:
                print(f"\n    error saving {nid}: {exc}", file=sys.stderr)
                errors += 1

            # Save progress after each note
            progress[str(fid)] = count
            _save_progress(output_dir, progress)

            print(f"\r    {fname}: {count}/{fcount}", end="", flush=True)
        print(f"\r    {fname}: {count} note(s)" + " " * 30)

        # Mark folder complete
        progress[str(fid)] = "done"
        _save_progress(output_dir, progress)

    # Write URL files (appending to any existing list)
    existing_entries = []
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            existing_entries = json.load(f)
    # Merge: existing entries + new entries, dedup by note_id
    seen = set()
    merged = []
    for e in existing_entries + entries:
        if e["note_id"] not in seen:
            seen.add(e["note_id"])
            merged.append(e)

    with open(urls_path, "w", encoding="utf-8") as f:
        for e in merged:
            f.write(f"{e['url']}\n")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\n{len(merged)} note(s) total. {saved} new, {skipped} already on disk, {errors} error(s).")
    print(f"  URLs  -> {urls_path}")
    print(f"  JSON  -> {json_path}")
    print(f"  Notes -> {notes_dir}")


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

        count = 0
        for note in client.iter_notes(folder_id=fid):
            nid = note["noteId"]
            count += 1
            try:
                path = os.path.join(notes_dir, f"{nid}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(note, f, indent=2, ensure_ascii=False)
                saved += 1
            except Exception as exc:
                print(f"\n    error saving {nid}: {exc}", file=sys.stderr)
                errors += 1
            print(f"\r    {fname}: {count}/{fcount} saved", end="", flush=True)
        print(f"\r    {fname}: {count} note(s) saved" + " " * 20)

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

    # Load cookies and optional credentials
    cookie_string = ""
    username = None
    password = None

    cookies_txt = os.path.join(os.path.dirname(args.config), "cookies.txt")
    if os.path.exists(cookies_txt):
        with open(cookies_txt) as f:
            cookie_string = f.read().strip()

    # Load config for credentials (and cookies fallback)
    config = {}
    if os.path.exists(args.config):
        config = load_config(args.config)
        if not cookie_string:
            cookie_string = config.get("cookies", "")
        username = config.get("username")
        password = config.get("password")

    if not cookie_string and not username:
        print(
            "Error: No cookie string or credentials found.\n"
            "Either:\n"
            "  - Create a cookies.txt with your browser cookie header, or\n"
            "  - Add \"username\" and \"password\" to config.json, or\n"
            "  - Add a \"cookies\" field to config.json",
            file=sys.stderr,
        )
        sys.exit(1)

    da = DASession(cookie_string=cookie_string, username=username, password=password)

    # If no cookies, login with credentials
    if not cookie_string:
        if not da.login():
            sys.exit(1)

    da.init()

    client = DANotesClient(da, request_delay=args.delay)
    folders = resolve_folders(da, args.folders)

    if not folders:
        print("No folders to scrape.", file=sys.stderr)
        sys.exit(1)

    total = sum(f.get("count", 0) for f in folders if isinstance(f.get("count"), int))
    print(f"Scraping {len(folders)} folder(s) ({total} notes):")
    for f in folders:
        print(f"  - {f['title']}: {f.get('count', '?')}")
    print()

    if args.mode == "both":
        # Single pass: paginate once, write both URL list and per-note JSON files
        run_both(client, folders, args.output)
    elif args.mode == "list":
        run_list(client, folders, args.output)
    elif args.mode == "extract":
        run_extract(client, folders, args.output)


if __name__ == "__main__":
    main()
