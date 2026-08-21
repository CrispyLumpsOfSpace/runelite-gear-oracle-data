#!/usr/bin/env python3
"""Derives each row's `_cite` block from the prose already in its `description` field.

`description` is the field of record and is never rewritten: it is what the plugin binds and
what carries a row's scope exclusions, which are prose and have no machine-checkable form.
`_cite` is the machine-checkable half of the same statement — the URLs and the verbatim quotes
pulled out of that prose, so tools/verify_sources.py can hold them against the live wiki.

Rerunnable: an existing `_cite` is replaced wholesale, so running twice is running once. The
result is written through tools/format_data.canonical, so a rerun cannot reflow a table away
from the layout validate.py enforces.

Usage:  migrate_sources.py [--check] [file ...]     default: every data/v1 table
        --check   report what would change and exit 1 if anything would, writing nothing
"""
import json
import re
import sys
from pathlib import Path

import format_data

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data/v1"
VERIFIED = "2026-08-21"

# Balanced parens are allowed inside the path so that Guardian_(Chambers_of_Xeric) survives.
URL = re.compile(r"https?://(?:[^\s\"')(]|\([^\s)]*\))+")
# A quoted span is a citation quote when it reads as prose. A two-word span is almost always a
# monster or item name the row is matching on ("Verzik Vitur"), not something a source said.
MIN_QUOTE_WORDS = 3
MIN_QUOTE_CHARS = 10
# The prose marker the tables already use for a value no source supports.
NO_CITATION = "CITATION-NONE"
# Pipeline-written files. Their only `source` is the whole-dataset attribution in `_meta`,
# which names the licence rather than a claim, so there is nothing here to quote-check.
NOT_CITED = set(format_data.GENERATED)


def kind_of(url):
    if "oldschool.runescape.wiki" in url:
        return "wiki"
    if "twitter.com" in url or "x.com" in url:
        return "tweet"
    if "docs.google.com" in url:
        return "sheet"
    return "web"


def quotes_in(text):
    """(start, quote) for every quoted span in the prose that reads as a quotation."""
    found = []
    for match in re.finditer(r'"([^"]+)"', text):
        quote = match.group(1).strip()
        if len(quote) >= MIN_QUOTE_CHARS and len(quote.split()) >= MIN_QUOTE_WORDS:
            found.append((match.start(), quote))
    return found


def citations_for(description):
    """The `_cite` list a description implies, or [] when it names nothing checkable."""
    urls = [(m.start(), m.end(), m.group(0).rstrip(".,;")) for m in URL.finditer(description)]
    quotes = quotes_in(description)

    if not urls:
        if quotes:
            # The prose quotes a source it does not link. verify_sources.py --derive-urls can
            # propose the article, but only a match against the live page may fill it in.
            return [{"kind": "unsourced", "quotes": [q for _, q in quotes],
                     "verified": VERIFIED}]
        if NO_CITATION in description:
            return [{"kind": "none", "quotes": [], "verified": VERIFIED}]
        return []

    # A quote belongs to the URL with the least prose between them, in either direction: the
    # tables write both `URL "quote"` and `"quote" (URL)`.
    assigned = {url: [] for _, _, url in urls}
    for position, quote in quotes:
        end = position + len(quote)
        nearest = min(urls, key=lambda u: min(abs(position - u[1]), abs(u[0] - end)))[2]
        if quote not in assigned[nearest]:
            assigned[nearest].append(quote)

    seen, cites = set(), []
    for _, _, url in urls:
        if url in seen:
            continue
        seen.add(url)
        cites.append({"kind": kind_of(url), "url": url,
                      "quotes": assigned[url], "verified": VERIFIED})
    return cites


def scan_string(text, start):
    """The end index (past the closing quote) of the JSON string literal opening at `start`."""
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string at %d" % start)


def scan_array(text, start):
    """The end index (past the closing bracket) of the JSON array opening at `start`."""
    depth, i = 0, start
    while i < len(text):
        c = text[i]
        if c == '"':
            i = scan_string(text, i)
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unterminated array at %d" % start)


def strip_existing(text):
    """The file with every `"_cite": [...]` entry and its separating comma removed."""
    while True:
        match = re.search(r'(,?)\s*"_cite"\s*:\s*(?=\[)', text)
        if not match:
            return text
        end = scan_array(text, text.index("[", match.end() - 1))
        # Exactly one of the separating commas goes with it: the leading one when there is
        # one, else the trailing one.
        if match.group(1):
            text = text[:match.start(1)] + text[end:]
            continue
        tail = re.match(r"\s*,", text[end:])
        text = text[:match.start()] + text[end + (tail.end() if tail else 0):]


def row_descriptions(doc):
    """The prose of each row of the table, in file order.

    Only a row of the table itself is a citable claim. `description` is also the name of the UI
    copy inside a row's nested option blocks (encounter-gear.json, required-weapon-immunities
    .json), and that copy cites nothing.
    """
    return [row["description"] for row in doc
            if isinstance(row, dict) and isinstance(row.get("description"), str)]


def description_spans(text, expected):
    """(key_start, value_end, prose) for each row description, matched against `expected`.

    A `"description":` inside a string value, or on a nested option block, would be a false
    hit; walking string literals from the top rules out the first, and taking spans only in the
    order their values appear in `expected` rules out the second.
    """
    spans = []
    for match in re.finditer(r'"description"\s*:\s*(?=")', text):
        if len(spans) == len(expected):
            break
        value_start = text.index('"', match.end() - 1)
        value_end = scan_string(text, value_start)
        value = json.loads(text[value_start:value_end])
        if value == expected[len(spans)]:
            spans.append((match.start(), value_end, value))
    return spans


def render(cites, pad):
    """`"_cite": [...]`, spliced in beside the row's prose; format_data then lays it out.

    `pad` is the literal indent of the row's `description` line, kept only so the intermediate
    text stays readable when a splice has to be debugged.
    """
    if pad is None:
        return ', "_cite": ' + json.dumps(cites, ensure_ascii=False, separators=(", ", ": "))
    inner = ",\n".join(
        pad + " " + json.dumps(c, ensure_ascii=False, separators=(", ", ": "))
        for c in cites)
    return ",\n" + pad + '"_cite": [\n' + inner + "\n" + pad + "]"


def carry_forward(fresh, previous):
    """The freshly derived citations, keeping what only verification could have added.

    A URL derived by verify_sources.py --derive-urls, and the date a check stamped, are not
    recoverable from the prose, so rederiving from the prose alone would throw them away.
    """
    merged = []
    for cite in fresh:
        match = next((p for p in previous
                      if (cite.get("url") and p.get("url") == cite["url"])
                      or (not cite.get("url") and p.get("quotes") == cite["quotes"])), None)
        if match:
            cite = dict(cite, verified=match.get("verified", cite["verified"]))
            if not cite.get("url") and match.get("url"):
                cite = {"kind": match["kind"], "url": match["url"],
                        "quotes": cite["quotes"], "verified": cite["verified"]}
        merged.append(cite)
    return merged


def existing_cites(text):
    """Each row's current `_cite` list, in the order description_spans walks the file."""
    return [row.get("_cite") or [] for row in json.loads(text)
            if isinstance(row, dict) and isinstance(row.get("description"), str)]


def migrate(path, cites_for=None):
    """Rewrites one table's `_cite` blocks; returns (rows touched, new text).

    `cites_for(description, ordinal)` supplies each row's citation list, so verify_sources.py
    can write back checked dates and derived URLs through this same editor.
    """
    original = path.read_text(encoding="utf-8")
    if cites_for is None:
        previous = existing_cites(original)
        cites_for = (lambda description, ordinal:
                     carry_forward(citations_for(description), previous[ordinal]))
    text = strip_existing(original)
    # Cross-check against the parsed document: a miscounted span means the scanner is wrong
    # and the file must not be written.
    parsed = row_descriptions(json.loads(text))
    spans = description_spans(text, parsed)
    if [s for _, _, s in spans] != parsed:
        raise SystemExit("%s: description scan disagrees with the parsed document" % path.name)

    touched = 0
    for ordinal, (key_start, value_end, description) in reversed(list(enumerate(spans))):
        cites = cites_for(description, ordinal)
        if not cites:
            continue
        line_start = text.rfind("\n", 0, key_start) + 1
        prefix = text[line_start:key_start]
        text = text[:value_end] + render(cites, prefix if not prefix.strip() else None) \
            + text[value_end:]
        touched += 1
    return touched, format_data.canonical(json.loads(text))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    paths = [Path(a) for a in args] or sorted(DATA.glob("*.json"))
    changed, total, files = [], 0, 0
    for path in paths:
        if path.name in NOT_CITED:
            continue
        touched, text = migrate(path)
        total += touched
        if text != path.read_text(encoding="utf-8"):
            changed.append(path.name)
            if not check:
                path.write_text(text, encoding="utf-8")
        if touched:
            files += 1
            print("%-40s %3d rows cited" % (path.name, touched))
    print("%d rows across %d files" % (total, files))
    if check and changed:
        print("stale _cite blocks in:", ", ".join(changed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
