#!/usr/bin/env python3
"""Rewrites every hand-authored data/v1 table in the repository's one canonical JSON layout.

Canonical is `json.dumps(indent=1, ensure_ascii=False)` plus a trailing newline: every object
and array member on its own line, one space per level, key order untouched. One layout means a
row's diff is the row, not the reflow of the line it shared with four others.

The pipeline-written files own their own form instead, because expanding a 1.5MB compact
bestiary to one line per field would multiply it: tools/fetch_data.py and tools/manifest.py are
canonical for monsters.json, equipment.json, meta.json and manifest.json. vectors/ is not
formatted at all (see NOTICE).

tools/validate.py fails the publish when a file differs from what this writes.

Usage:  format_data.py [--check] [file ...]     default: every hand-authored data/v1 table
        --check   name the files that would change and exit 1, writing nothing
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data/v1"
# Written by fetch_data.py and manifest.py, which are canonical for them.
GENERATED = {"manifest.json", "meta.json", "monsters.json", "equipment.json"}


def canonical(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def formatted(path):
    """The canonical text of one table, or None when it is not this script's to write."""
    if path.name in GENERATED:
        return None
    return canonical(json.loads(path.read_text(encoding="utf-8")))


def tables():
    return [p for p in sorted(DATA.glob("*.json")) if p.name not in GENERATED]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    paths = [Path(a) for a in args] or tables()
    changed = []
    for path in paths:
        text = formatted(path)
        if text is None or text == path.read_text(encoding="utf-8"):
            continue
        changed.append(path.name)
        if not check:
            path.write_text(text, encoding="utf-8")
    print("%s %d of %d files" % ("would reformat" if check else "reformatted",
                                 len(changed), len(paths)))
    if changed:
        print("  " + ", ".join(changed))
    return 1 if check and changed else 0


if __name__ == "__main__":
    sys.exit(main())
