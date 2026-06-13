#!/usr/bin/env python3
"""
probe_to_anki.py — Import probe files into Anki via AnkiConnect.

Usage:
    python3 scripts/probe_to_anki.py docs/probes/              # all files in dir
    python3 scripts/probe_to_anki.py docs/probes/phase-1.md    # single file
    python3 scripts/probe_to_anki.py docs/probes/ --dry-run    # preview only
    python3 scripts/probe_to_anki.py --query-flagged           # show blue-flagged cards

Requires: Anki open with AnkiConnect plugin installed (default port 8765).
WSL2: AnkiConnect must bind to 0.0.0.0 (see JOURNAL_ANKI_PLAN.md §3.2).
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path


def _windows_host_ip() -> str:
    """In WSL2, the Windows host is the default route gateway."""
    import subprocess
    try:
        out = subprocess.check_output(["ip", "route"], text=True)
        for line in out.splitlines():
            if line.startswith("default"):
                return line.split()[2]
    except Exception:
        pass
    return "localhost"


_HOST = _windows_host_ip()
ANKI_URL = f"http://{_HOST}:8765"
ANKI_VERSION = 6


# ---------------------------------------------------------------------------
# AnkiConnect helpers
# ---------------------------------------------------------------------------

def anki(action: str, **params) -> object:
    payload = json.dumps({
        "action": action,
        "version": ANKI_VERSION,
        "params": params,
    }).encode()
    req = urllib.request.Request(
        ANKI_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    error = result.get("error")
    if error:
        raise RuntimeError(f"AnkiConnect error ({action}): {error}")
    return result["result"]


def ensure_deck(deck_name: str) -> None:
    anki("createDeck", deck=deck_name)


def add_notes_deduped(notes: list[dict]) -> tuple[int, int]:
    """
    Check each note before adding. Returns (added, skipped_dupes).
    Uses canAddNotesWithErrorDetail to filter duplicates before calling
    addNotes — avoids the per-note error list that addNotes returns for
    duplicates, which AnkiConnect surfaces inconsistently.
    """
    if not notes:
        return 0, 0

    checks = anki("canAddNotesWithErrorDetail", notes=notes)
    eligible = [n for n, c in zip(notes, checks) if c.get("canAdd")]
    skipped = len(notes) - len(eligible)

    added = 0
    if eligible:
        results = anki("addNotes", notes=eligible)
        added = sum(1 for r in results if r is not None)

    return added, skipped


def query_flagged(deck: str = "Rhizome") -> list[int]:
    """Return note IDs flagged blue (flag:4) in the given deck."""
    return anki("findNotes", query=f"flag:4 deck:{deck}")


def get_notes_info(note_ids: list[int]) -> list[dict]:
    return anki("notesInfo", notes=note_ids)


# ---------------------------------------------------------------------------
# Probe file parser
# ---------------------------------------------------------------------------

CARD_BLOCK_RE = re.compile(r"```markdown\n(.*?)```", re.DOTALL)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TAGS_RE = re.compile(r"^tags:\s*\[([^\]]*)\]", re.MULTILINE)
DECK_RE = re.compile(r"^deck:\s*(.+)", re.MULTILINE)
TYPE_RE = re.compile(r"^type:\s*(.+)", re.MULTILINE)
EXTRA_RE = re.compile(r"\nExtra:\s*(.+?)$", re.DOTALL)


def parse_tags(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def parse_card_block(block: str) -> dict | None:
    fm_match = FRONTMATTER_RE.match(block)
    if not fm_match:
        return None

    fm = fm_match.group(1)
    body = block[fm_match.end():]

    type_m = TYPE_RE.search(fm)
    deck_m = DECK_RE.search(fm)
    tags_m = TAGS_RE.search(fm)

    if not type_m or not deck_m:
        return None

    card_type = type_m.group(1).strip()
    deck = deck_m.group(1).strip()
    tags = parse_tags(tags_m.group(1)) if tags_m else []

    # Extract Extra from body
    extra = ""
    extra_m = EXTRA_RE.search(body)
    if extra_m:
        extra = extra_m.group(1).strip()
        body = body[: extra_m.start()].strip()
    else:
        body = body.strip()

    if card_type == "cloze":
        return {
            "type": "cloze",
            "deck": deck,
            "tags": tags,
            "fields": {"Text": body, "Back Extra": extra},
        }

    if card_type == "basic":
        qa_m = re.match(r"^Q:\s*(.*?)\n\nA:\s*(.*)$", body, re.DOTALL)
        if not qa_m:
            return None
        return {
            "type": "basic",
            "deck": deck,
            "tags": tags,
            "fields": {"Front": qa_m.group(1).strip(), "Back": qa_m.group(2).strip(), "Extra": extra},
        }

    if card_type == "image-occlusion":
        # Parsed but not synced — handled separately (see §1.2 of plan)
        return {
            "type": "image-occlusion",
            "deck": deck,
            "tags": tags,
            "raw": body,
            "extra": extra,
        }

    return None


def parse_probe_file(path: Path) -> list[dict]:
    content = path.read_text(encoding="utf-8")
    cards = []
    for block in CARD_BLOCK_RE.finditer(content):
        card = parse_card_block(block.group(1))
        if card:
            cards.append(card)
    return cards


# ---------------------------------------------------------------------------
# Build AnkiConnect note objects
# ---------------------------------------------------------------------------

MODEL_NAMES = {
    "basic": "Basic",
    "cloze": "Cloze",
}


def build_note(card: dict) -> dict:
    return {
        "deckName": card["deck"],
        "modelName": MODEL_NAMES[card["type"]],
        "fields": card["fields"],
        "tags": card["tags"],
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Import probe markdown files into Anki.")
    parser.add_argument("paths", nargs="*", help="Probe .md file(s) or directory")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print without adding")
    parser.add_argument("--query-flagged", action="store_true", help="Show blue-flagged cards and exit")
    args = parser.parse_args()

    # --- Flagged card review mode ---
    if args.query_flagged:
        print("Querying blue-flagged cards (flag:4 deck:Rhizome)...\n")
        note_ids = query_flagged()
        if not note_ids:
            print("No flagged cards found.")
            return
        notes_info = get_notes_info(note_ids)
        print(f"{len(notes_info)} flagged card(s) need review:\n")
        for i, note in enumerate(notes_info, 1):
            fields = note.get("fields", {})
            first_field = next(iter(fields.values()), {})
            preview = first_field.get("value", "")[:120]
            tags = " ".join(note.get("tags", []))
            print(f"  [{i}] {preview}")
            if tags:
                print(f"       tags: {tags}")
            print()
        return

    # --- Sync mode ---
    if not args.paths:
        parser.error("Provide at least one path, or use --query-flagged")

    files: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.md")))
        elif path.is_file():
            files.append(path)
        else:
            print(f"Warning: {p} not found, skipping", file=sys.stderr)

    if not files:
        print("No probe files found.", file=sys.stderr)
        sys.exit(1)

    all_cards: list[dict] = []
    image_occlusion_pending: list[dict] = []

    for f in files:
        cards = parse_probe_file(f)
        syncable = [c for c in cards if c["type"] in MODEL_NAMES]
        io_cards = [c for c in cards if c["type"] == "image-occlusion"]
        print(f"  {f.name}: {len(syncable)} syncable, {len(io_cards)} image-occlusion (manual)")
        all_cards.extend(syncable)
        image_occlusion_pending.extend(io_cards)

    print(f"\n{len(all_cards)} card(s) to sync.")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for c in all_cards:
            print(f"\n[{c['type'].upper()}] {c['deck']} | tags: {c['tags']}")
            for k, v in c["fields"].items():
                if v:
                    print(f"  {k}: {v[:80]}{'...' if len(v) > 80 else ''}")
        if image_occlusion_pending:
            print(f"\n[IMAGE OCCLUSION — {len(image_occlusion_pending)} pending manual creation]")
            for c in image_occlusion_pending:
                print(f"  deck: {c['deck']} | tags: {c['tags']}")
        return

    if not all_cards and not image_occlusion_pending:
        print("Nothing to sync.")
        return

    # Ensure decks exist
    decks = {c["deck"] for c in all_cards + image_occlusion_pending}
    for deck in sorted(decks):
        ensure_deck(deck)
        print(f"  Deck ready: {deck}")

    # Add notes with dedup
    notes = [build_note(c) for c in all_cards]
    added, skipped = add_notes_deduped(notes)
    print(f"\n✓ Added {added} card(s). {skipped} duplicate(s) skipped.")

    # Image Occlusion summary
    if image_occlusion_pending:
        print(f"\n⚠  {len(image_occlusion_pending)} Image Occlusion card(s) require manual creation in Anki desktop:")
        for c in image_occlusion_pending:
            preview = c["raw"][:80].replace("\n", " ")
            print(f"  [{c['deck']}] {preview}")


if __name__ == "__main__":
    main()