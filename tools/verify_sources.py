#!/usr/bin/env python3
"""Holds every `_cite` quote against the page it cites, on the live OSRS Wiki.

This is the manual half of the validation ladder, not a gate: a wiki article can be reworded
the day after it was cited without the fact it stated changing, so a quote that stops matching
is a prompt to go and look, never a reason to block a publish. tools/validate.py checks the
SHAPE of a citation and blocks; this checks its CONTENT and reports.

The workflow: run it, read the NOT-FOUND list, fix or re-quote what is genuinely wrong, then
rerun with --update-dates to stamp today onto everything that did match.

Non-wiki sources (JMod tweets, Bitterkoekje's sheet) are reported as MANUAL rather than
fetched: they are neither reliably reachable nor stable enough to machine-check.

Usage:  verify_sources.py [--update-dates] [--derive-urls] [--strict] [--limit N] [file ...]
        --update-dates  stamp today on citations whose every quote matched verbatim
        --derive-urls   for a citation whose prose quotes an article it never linked, propose
                        the article and, when the quote is there, write the URL in
        --strict        exit 1 on any NOT-FOUND (for a human run; CI should not pass this)
        --limit N       stop after N wiki pages, to sample a big table politely
"""
import datetime
import json
import re
import sys
from pathlib import Path

import migrate_sources as migrate
import wiki_pages

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data/v1"
TODAY = datetime.date.today().isoformat()
WIKI = "https://oldschool.runescape.wiki/w/"

VERIFIED, PARTIAL, NOT_FOUND, LINK_ONLY, MANUAL, MISSING = (
    "VERIFIED", "PARTIAL", "NOT-FOUND", "LINK-ONLY", "MANUAL", "PAGE-MISSING")


def rows_of(path):
    """Every row carrying a `description`, in the order migrate.description_spans walks them."""
    return [row for row in json.loads(path.read_text(encoding="utf-8"))
            if isinstance(row, dict) and isinstance(row.get("description"), str)]


def label(row):
    for field in ("id", "key", "name", "monsterClass"):
        if isinstance(row.get(field), str):
            return row[field]
    return "?"


def candidate_titles(row, quote):
    """Article titles a quote with no link might have come from, best guess first.

    The prose convention these tables use is `Article name "the quote"`, so the capitalised
    run immediately before the quote is the strongest candidate; the row's own name is the
    fallback. Nothing is written on a guess alone: derive_urls only keeps a candidate whose
    page actually contains the quote.
    """
    titles = []
    before = row["description"].split('"' + quote + '"')[0]
    run = re.search(r"([A-Z][\w'-]*(?: [a-z]{1,4})?(?: [\w'-]+){0,3})\s*[—:-]?\s*$", before)
    if run:
        words = run.group(1).split()
        for size in range(len(words), 0, -1):
            titles.append(" ".join(words[:size]))
    for field in ("name", "label"):
        if isinstance(row.get(field), str):
            titles.append(row[field])
    return list(dict.fromkeys(t for t in titles if len(t) > 2))


class Budget:
    """The cap --limit puts on how many distinct pages one run fetches."""

    def __init__(self, limit):
        self.limit = limit
        self.pages = set()

    def allows(self, title):
        if title in self.pages:
            return True
        if self.limit and len(self.pages) >= self.limit:
            return False
        self.pages.add(title)
        return True


def check_citation(cite, row, budget, derive):
    """(status, detail, updated cite) for one citation."""
    cite = dict(cite)
    if cite["kind"] == "unsourced" and derive:
        for title in candidate_titles(row, cite["quotes"][0]):
            if not budget.allows(title):
                break
            page = wiki_pages.fetch(title)
            if page["missing"]:
                continue
            if all(wiki_pages.find_quote(page, q) for q in cite["quotes"]):
                cite["kind"] = "wiki"
                cite["url"] = WIKI + title.replace(" ", "_")
                cite = {"kind": cite["kind"], "url": cite["url"],
                        "quotes": cite["quotes"], "verified": cite["verified"]}
                break

    if cite["kind"] != "wiki":
        return MANUAL, cite["kind"], cite

    title = wiki_pages.title_of(cite["url"])
    if not title or not budget.allows(title):
        return MANUAL, "not fetched", cite
    page = wiki_pages.fetch(title)
    if page["missing"]:
        return MISSING, title, cite
    if not cite["quotes"]:
        return LINK_ONLY, title, cite

    results = [(q, wiki_pages.find_quote(page, q)) for q in cite["quotes"]]
    misses = [q for q, hit in results if not hit]
    if misses:
        return NOT_FOUND, "; ".join(q[:70] for q in misses), cite
    if any(str(hit).startswith("partial") for _, hit in results):
        return PARTIAL, title, cite
    return VERIFIED, title, cite


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    update = "--update-dates" in flags
    derive = "--derive-urls" in flags
    limit = next((int(f.split("=")[1]) for f in flags if f.startswith("--limit=")), 0)
    if "--limit" in flags:
        limit = int(args.pop(0))
    paths = [Path(a) for a in args] or sorted(DATA.glob("*.json"))
    budget = Budget(limit)

    counts, report, changed = {}, [], []
    for path in paths:
        if path.name in migrate.NOT_CITED:
            continue
        # The ordinal is the row's position among the file's `description` keys, which is what
        # migrate_sources.migrate hands back when it rewrites the block.
        rows = list(enumerate(rows_of(path)))
        if not any(r.get("_cite") for _, r in rows):
            continue
        updates = {}
        for ordinal, row in rows:
            if not row.get("_cite"):
                continue
            fresh = []
            for cite in row["_cite"]:
                status, detail, checked = check_citation(cite, row, budget, derive)
                if update and status in (VERIFIED, LINK_ONLY):
                    checked = dict(checked, verified=TODAY)
                fresh.append(checked)
                counts[status] = counts.get(status, 0) + 1
                if status not in (VERIFIED, LINK_ONLY, MANUAL):
                    report.append((status, path.name, label(row), detail))
            updates[ordinal] = fresh
        if update or derive:
            _, text = migrate.migrate(
                path, lambda description, ordinal: updates.get(ordinal, []))
            if text != path.read_text(encoding="utf-8"):
                path.write_text(text, encoding="utf-8")
                changed.append(path.name)

    for status, name, key, detail in sorted(report):
        print("%-12s %-34s %-28s %s" % (status, name, key, detail))
    print()
    print("%d citations: %s" % (sum(counts.values()),
                                ", ".join("%d %s" % (v, k) for k, v in sorted(counts.items()))))
    if changed:
        print("rewrote:", ", ".join(changed), "— rerun tools/manifest.py")
    return 1 if ("--strict" in flags and counts.get(NOT_FOUND)) else 0


if __name__ == "__main__":
    sys.exit(main())
