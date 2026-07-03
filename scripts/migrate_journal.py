#!/usr/bin/env python3
"""
migrate_journal.py — split a journal-anki style docs/journal.md into
one frontmattered file per entry under docs/journal/.

Pure text transformation. No API calls, no LLM, no tokens spent.

Usage:
    python3 migrate_journal.py <repo-name> <path/to/journal.md> [output_dir]

Example:
    python3 migrate_journal.py sentinel-l7 docs/journal.md docs/journal

What it assumes about the input (matches the journal-anki spec's existing
header style, NOT the older LEARNING_LOG.md Pattern/Decision-only dialect):

    ## Phase 6 — Sentinel-L7 Dashboard (TraceQL metrics) — 2026-06-12
    cross-ref: observability
    Files: app/Services/AxiomProcessorService.php, docs/adr/0024-x.md

    ### Pattern: Competing Consumers
    ...prose...

    ### Decision: Something
    ...prose...

It does NOT invent tags beyond what's already named in ### Pattern: /
### Anti-Pattern Avoided: / ### Decision: headers, does NOT call any AI to
improve prose, and does NOT guess at content. Anything genuinely ambiguous
is left for you to review afterward (see the printed summary at the end).
"""

import re
import sys
from pathlib import Path

PHASE_HEADER_RE = re.compile(
    r"^##\s+Phase\s+(?P<phase>[\w.()\s]+?)\s+—\s+(?P<title>.+?)\s+—\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$",
    re.MULTILINE,
)
CROSS_REF_RE = re.compile(r"^cross-ref:\s*(.+)$", re.MULTILINE)
FILES_RE = re.compile(r"^Files:\s*(.+)$", re.MULTILINE)
SECTION_NAME_RE = re.compile(
    r"^###\s+(Pattern|Anti-Pattern Avoided|Decision):\s*(.+)$", re.MULTILINE
)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def tag_from_name(name: str) -> str:
    """Turn a formal pattern/decision name into a tag-safe slug."""
    return slugify(name)


def split_entries(raw_text: str):
    """Yield (header_match, entry_body_text) for each phase block."""
    matches = list(PHASE_HEADER_RE.finditer(raw_text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        yield m, raw_text[start:end]


def build_frontmatter(repo, phase, title, date, tags, cross_ref, entry_id, files):
    lines = ["---"]
    lines.append(f"id: {entry_id}")
    lines.append(f"repo: {repo}")
    lines.append(f'title: "{title}"')
    lines.append(f"date: {date}")
    if phase:
        lines.append(f"phase: {phase}")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    else:
        lines.append("tags: []")
    if cross_ref:
        lines.append(f"cross_ref: {cross_ref}")
        lines.append(f"cross_ref_id: {entry_id}")
    if files:
        lines.append(f"files: [{', '.join(files)}]")
    lines.append("---")
    return "\n".join(lines)


def migrate(repo, journal_path, out_dir):
    raw_text = journal_path.read_text(encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    flagged = []

    for header_match, body in split_entries(raw_text):
        phase = header_match.group("phase").strip()
        title = header_match.group("title").strip()
        date = header_match.group("date").strip()

        cross_ref_match = CROSS_REF_RE.search(body)
        cross_ref = cross_ref_match.group(1).strip() if cross_ref_match else None

        files_match = FILES_RE.search(body)
        files = []
        if files_match:
            files = [f.strip() for f in files_match.group(1).split(",") if f.strip()]

        tags = sorted({tag_from_name(name) for _, name in SECTION_NAME_RE.findall(body)})
        if not tags:
            flagged.append(f"{title} ({date}) — no Pattern/Anti-Pattern/Decision "
                            f"names found to seed tags; review manually.")

        # Strip the cross-ref and Files lines from the body since they now
        # live in frontmatter — keep everything else (the prose) untouched.
        clean_body = CROSS_REF_RE.sub("", body)
        clean_body = FILES_RE.sub("", clean_body)
        clean_body = clean_body.strip("\n") + "\n"

        date_compact = date.replace("-", "")
        slug = slugify(title)
        entry_id = f"{repo}-{date_compact}-{slug}"
        filename = f"{entry_id}.md"

        frontmatter = build_frontmatter(
            repo=repo, phase=phase, title=title, date=date,
            tags=tags, cross_ref=cross_ref, entry_id=entry_id, files=files,
        )

        full_content = frontmatter + "\n\n" + clean_body
        out_path = out_dir / filename

        if out_path.exists():
            flagged.append(f"{filename} already exists — skipped, did not overwrite.")
            continue

        out_path.write_text(full_content, encoding="utf-8")
        written.append(filename)

    print(f"\nMigrated {len(written)} entries from {journal_path} into {out_dir}/\n")
    for f in written:
        print(f"  wrote  {f}")

    if flagged:
        print(f"\n{len(flagged)} item(s) flagged for manual review:\n")
        for f in flagged:
            print(f"  - {f}")
    else:
        print("\nNothing flagged.")

    print(
        "\nNote: tags were seeded only from existing ### Pattern: / "
        "### Anti-Pattern Avoided: / ### Decision: names already in the "
        "source file. No content was rewritten or invented. Review tags "
        "before committing if you want richer coverage."
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    repo_name = sys.argv[1]
    journal_file = Path(sys.argv[2])
    output_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("docs/journal")

    if not journal_file.exists():
        print(f"Error: {journal_file} not found.")
        sys.exit(1)

    migrate(repo_name, journal_file, output_dir)
