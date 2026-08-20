#!/usr/bin/env python3
"""Writes a markdown summary of the working tree's dataset changes against HEAD, for the
promotion PR body: per-file row counts with added/removed/changed examples by name, so a
reviewer sees what a refresh did without reading the row-by-row diff."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Derivatives of the files summarised below; their diffs carry no independent information.
SKIP = {"data/v1/manifest.json", "data/v1/meta.json"}
MAX_EXAMPLES = 8

FOOTER = (
    "\n---\nStaged by the refresh workflow. Merging serves this to clients; test first by"
    " launching the plugin with `GEAR_ORACLE_DATA_BRANCH=staging`.\n"
)


def changed_files():
    out = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", "data", "fixtures"],
        capture_output=True, text=True, cwd=ROOT, check=True).stdout.split()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "--", "data", "fixtures"],
        capture_output=True, text=True, cwd=ROOT, check=True).stdout.split()
    return [p for p in out + untracked if p.endswith(".json") and p not in SKIP]


def head_copy(path):
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path}"], capture_output=True, text=True, cwd=ROOT)
    return json.loads(proc.stdout) if proc.returncode == 0 else None


def records(doc):
    """Any published shape as {key: row}: a rows file, a bare list, or a single mapping."""
    if isinstance(doc, list):
        return keyed(doc)
    if isinstance(doc, dict):
        if isinstance(doc.get("rows"), list):
            return keyed(doc["rows"])
        mappings = [v for k, v in doc.items() if not k.startswith("_") and isinstance(v, dict)]
        if len(mappings) == 1:
            return {str(k): v for k, v in mappings[0].items()}
    return None


def keyed(rows):
    out = {}
    for row in rows:
        key = None
        if isinstance(row, dict):
            for f in ("id", "item_name", "name", "page_name", "key"):
                if f in row and row[f] not in (None, "", []):
                    key = f"{f}={json.dumps(row[f], sort_keys=True)}"
                    break
        if key is None:
            key = json.dumps(row, sort_keys=True)
        while key in out:
            key += "'"
        out[key] = row
    return out


def label(row, key):
    if isinstance(row, dict):
        for f in ("name", "item_name", "page_name"):
            v = row.get(f)
            if isinstance(v, str) and v:
                anchor = row.get("version_anchor")
                return f"{v} ({anchor})" if anchor else v
    return key


def examples(keys, side):
    shown = [label(side[k], k) for k in list(keys)[:MAX_EXAMPLES]]
    more = len(keys) - len(shown)
    return ", ".join(shown) + (f" (+{more} more)" if more > 0 else "")


def summarise(path):
    new_doc = json.loads((ROOT / path).read_text(encoding="utf-8"))
    old, new = records(head_copy(path)), records(new_doc)
    if new is None or old is None:
        return f"### `{path}`\ncontent changed (no row shape to summarise)\n"
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    changed = [k for k in new if k in old and new[k] != old[k]]
    lines = [f"### `{path}` — {len(new)} rows (+{len(added)} / −{len(removed)}"
             f" / ~{len(changed)})"]
    if added:
        lines.append(f"- added: {examples(added, new)}")
    if removed:
        lines.append(f"- removed: {examples(removed, old)}")
    if changed:
        lines.append(f"- changed: {examples(changed, new)}")
    return "\n".join(lines) + "\n"


def main():
    files = changed_files()
    if not files:
        print("No dataset changes against the previous publish.")
        print(FOOTER)
        return
    print("Weekly dataset refresh, summarised against the previously published copy.\n")
    for path in files:
        try:
            print(summarise(path))
        except Exception as e:  # a summary must never block the publish
            print(f"### `{path}`\ncontent changed (summary failed: {e})\n")
    print(FOOTER)


if __name__ == "__main__":
    main()
