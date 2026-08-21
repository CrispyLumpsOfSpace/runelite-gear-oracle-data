#!/usr/bin/env python3
"""Validates a freshly fetched dataset before it is published.

The point of this repo is that a bad wiki edit or a Bucket API schema change breaks THIS
pipeline, visibly, instead of degrading every installed client — so this errs toward failing.
Checks each file's shape, its required fields, that row counts have not collapsed against the
previously published copy (a shrink beyond tolerance means the source query broke), and that
the published manifest still matches the files it hashes.
"""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

import format_data
import manifest

ROOT = Path(__file__).resolve().parent.parent
# The universe grows over time; a real update never removes more than a few rows at once.
SHRINK_TOLERANCE = 0.02


def show_head(relative):
    try:
        return subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            capture_output=True, text=True, cwd=ROOT, check=True).stdout
    except Exception:
        return None


def previous_counts():
    try:
        return json.loads(show_head("data/v1/meta.json")).get("counts", {})
    except Exception:
        return {}


def check_shrink(errors, name, now, before):
    if before and now < before * (1 - SHRINK_TOLERANCE):
        errors.append(f"{name}: row count collapsed {before} -> {now}")


# meta.json and manifest.json describe the publish itself rather than carrying rows.
NON_TABLE_FILES = {"manifest.json", "meta.json"}
# The wrapper keys a table uses when it also has to carry an _meta attribution block.
ROW_CONTAINER_KEYS = ("rows", "categories")


def row_container(doc):
    """The rows of a published table, or None when the document is not shaped like one."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        for key in ROW_CONTAINER_KEYS:
            container = doc.get(key)
            if isinstance(container, (list, dict)):
                return container
    return None


def previous_rows(name):
    """The last published rows of a table, or None when it is new or was unreadable."""
    try:
        return row_container(json.loads(show_head(f"data/v1/{name}")))
    except Exception:
        return None


def check_tables(errors):
    """Every published table parses, holds objects, and has not shrunk against the last publish.

    meta.json counts only the fetched tables, so without this an emptied mechanic file publishes
    cleanly and deletes that whole mechanic class from every installed client.
    """
    for path in sorted((ROOT / "data/v1").glob("*.json")):
        if path.name in NON_TABLE_FILES:
            continue
        try:
            doc = json.loads(path.read_text())
        except ValueError as error:
            errors.append(f"{path.name}: does not parse as JSON ({error})")
            continue
        rows = row_container(doc)
        if rows is None:
            errors.append(f"{path.name}: no row container, expected an array or one of "
                          f"{ROW_CONTAINER_KEYS}")
            continue
        if isinstance(rows, list):
            bad = [i for i, row in enumerate(rows) if not isinstance(row, dict)]
            if bad:
                errors.append(f"{path.name}: {len(bad)} rows are not objects "
                              f"(first at index {bad[0]})")
        if not rows:
            errors.append(f"{path.name}: is empty, a published table always carries a row")
            continue
        before = previous_rows(path.name)
        check_shrink(errors, path.name, len(rows), len(before) if before else None)


SOURCE_CODE_MARKERS = ("@PackagePrivate", "@NonFinal", "transient ", "{@link", "public static",
                       "private static", "} }")


def check_no_source_dumps(errors):
    """A row's prose field must not carry pasted Java.

    Three weapon-families rows once held 18KB of ItemSpec.java between them, glued ahead of the
    note the author wrote. It reached every client, and nothing here noticed.
    """
    for path in sorted((ROOT / "data/v1").glob("*.json")):
        try:
            rows = json.loads(path.read_text())
        except ValueError:
            continue  # check_tables reports the parse failure.
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for field, value in row.items():
                if not isinstance(value, str):
                    continue
                found = [m for m in SOURCE_CODE_MARKERS if m in value]
                if found:
                    errors.append(f"{path.name}: {row.get('key')}.{field} looks like pasted "
                                  f"source ({found[0]!r}, {len(value)} bytes)")


CITE_KINDS = {"wiki", "tweet", "sheet", "web", "unsourced", "none"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_citation(errors, where, cite):
    if not isinstance(cite, dict):
        errors.append(f"{where}: a _cite entry is not an object")
        return
    unknown = set(cite) - {"kind", "url", "quotes", "verified"}
    if unknown:
        errors.append(f"{where}: unknown _cite fields {sorted(unknown)}")
    if cite.get("kind") not in CITE_KINDS:
        errors.append(f"{where}: _cite kind {cite.get('kind')!r} is not one of {sorted(CITE_KINDS)}")
    verified = cite.get("verified")
    if not isinstance(verified, str) or not ISO_DATE.match(verified):
        errors.append(f"{where}: _cite verified {verified!r} is not an ISO date")
    else:
        try:
            datetime.date.fromisoformat(verified)
        except ValueError:
            errors.append(f"{where}: _cite verified {verified!r} is not a real date")
    quotes = cite.get("quotes")
    if not isinstance(quotes, list) or any(not isinstance(q, str) or not q.strip()
                                           for q in quotes):
        errors.append(f"{where}: _cite quotes must be a list of non-empty strings")
    url = cite.get("url")
    if cite.get("kind") in ("unsourced", "none"):
        if url is not None:
            errors.append(f"{where}: a {cite['kind']} _cite carries a url — it should be 'wiki'")
    elif not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{where}: _cite url {url!r} is not an https URL")


def check_citations(errors):
    """Every `_cite` block is well-formed. Structure only — the quotes themselves are held
    against the live wiki by tools/verify_sources.py, which reports rather than blocks."""
    for path in sorted((ROOT / "data/v1").glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except ValueError:
            continue  # check_tables reports the parse failure.

        def walk(node, key="?"):
            if isinstance(node, dict):
                key = next((node[f] for f in ("id", "key", "name") if isinstance(node.get(f), str)),
                           key)
                cites = node.get("_cite")
                if cites is not None:
                    where = f"{path.name}: {key}"
                    if not isinstance(cites, list) or not cites:
                        errors.append(f"{where}: _cite must be a non-empty list")
                    else:
                        for cite in cites:
                            check_citation(errors, where, cite)
                    if not isinstance(node.get("description"), str):
                        errors.append(f"{where}: carries _cite without a description")
                for value in node.values():
                    walk(value, key)
            elif isinstance(node, list):
                for value in node:
                    walk(value, key)

        walk(doc)


def check_stat_gaps(errors):
    """No row publishes a stat the wiki could not state as one number.

    The Bucket API drops a stat it cannot store numerically, so a band, a footnoted number and
    a blank parameter all reach the fetcher as an absent field. Coercing one to 0 publishes an
    override that outranks the game cache's real stat, so a gap appearing inside "ov" is that
    coercion.
    """
    try:
        report = json.loads((ROOT / "fixtures/v1/monster-stat-gaps.json").read_text())
    except (OSError, ValueError) as error:
        errors.append(f"monster-stat-gaps: unreadable ({error}) — run tools/fetch_data.py")
        return
    gaps = report.get("rows")
    if not isinstance(gaps, list):
        errors.append("monster-stat-gaps: no gap list — run tools/fetch_data.py")
        return
    gapped = {(g.get("page_name"), g.get("version_anchor"), g.get("field")) for g in gaps
              if isinstance(g, dict)}
    for name in ("data/v1/monsters.json", "fixtures/v1/monsters-full.json"):
        try:
            rows = json.loads((ROOT / name).read_text()).get("rows") or []
        except (OSError, ValueError):
            continue  # check_tables reports the parse failure.
        published = [(r.get("page_name"), r.get("version_anchor") or "", field)
                     for r in rows for field in (r.get("ov") or {})]
        leaked = sorted(set(published) & gapped)
        if leaked:
            errors.append(f"{Path(name).name}: publishes {len(leaked)} stats the wiki states no "
                          f"number for (e.g. {leaked[:3]}) — a parse failure became a value")


def check_format(errors):
    """Every hand-authored table is byte-identical to its canonical layout.

    Blocking rather than reporting: a table that reflows on the next tool run buries the row
    that actually changed in a whole-file diff.
    """
    for path in format_data.tables():
        try:
            if format_data.formatted(path) != path.read_text(encoding="utf-8"):
                errors.append(f"{path.name}: not in canonical layout — run tools/format_data.py")
        except ValueError:
            continue  # check_tables reports the parse failure.


def main():
    errors = []
    check_tables(errors)
    check_stat_gaps(errors)
    check_format(errors)
    check_no_source_dumps(errors)
    check_citations(errors)

    monsters = json.loads((ROOT / "data/v1/monsters.json").read_text())
    rows = monsters.get("rows")
    if not isinstance(rows, list) or len(rows) < 2500:
        errors.append(f"monsters: expected 2500+ rows, got {type(rows)} "
                      f"{len(rows) if isinstance(rows, list) else ''}")
    else:
        named = sum(1 for r in rows if r.get("name"))
        if named < len(rows) * 0.9:
            errors.append(f"monsters: only {named}/{len(rows)} rows carry a name")
        with_hp = sum(1 for r in rows if "hitpoints" in r)
        if with_hp < len(rows) * 0.9:
            errors.append(f"monsters: only {with_hp}/{len(rows)} rows carry hitpoints — schema moved?")
        overridden = sum(1 for r in rows if r.get("ov"))
        # The overrides are the placeholders, versions and disagreements — a collapse to near
        # zero means the cache diff broke, an explosion means the cache dump did.
        if not 200 < overridden < len(rows) * 0.6:
            errors.append(f"monsters: {overridden} rows carry stat overrides — expected a few hundred")
        full = json.loads((ROOT / "fixtures/v1/monsters-full.json").read_text())
        if len(full.get("rows", [])) != len(rows):
            errors.append("monsters-full fixture row count differs from the published bestiary")
        # A failed wiki template renders inline HTML where a value should be; fetch_data.clean
        # drops those, so any tag reaching here means that screen broke.
        leaked = [r.get("name") for r in rows
                  if any(isinstance(v, str) and "<" in v for v in r.values())]
        if leaked:
            errors.append(f"monsters: wiki markup leaked into {len(leaked)} rows "
                          f"(e.g. {leaked[:3]})")

    equipment = json.loads((ROOT / "data/v1/equipment.json").read_text())
    categories = equipment.get("categories", {})
    if len(categories) < 1300:
        errors.append(f"equipment: only {len(categories)} weapon categories — join broke?")
    full = json.loads((ROOT / "fixtures/v1/equipment-full.json").read_text())
    if not isinstance(full, list) or len(full) < 4000:
        errors.append(f"equipment-full: expected 4000+ joined rows, got "
                      f"{len(full) if isinstance(full, list) else type(full)}")
    else:
        slots = {r.get("slot") for r in full}
        for slot in ("weapon", "2h", "ammo", "head", "body"):
            if slot not in slots:
                errors.append(f"equipment-full: no rows with slot '{slot}' — join broke?")

    attributes = json.loads((ROOT / "fixtures/v1/reference-attributes.json").read_text())
    if len(attributes.get("attributesById", {})) < 2500:
        errors.append("reference-attributes: id map collapsed")
    weapons = json.loads((ROOT / "fixtures/v1/reference-weapon-categories.json").read_text())
    if len(weapons.get("weapons", [])) < 1300:
        errors.append("reference-weapon-categories: weapon list collapsed")

    # The runtime files travel one at a time from raw hosting; the attribution has to be
    # in-band to travel with them.
    for name, doc in (("monsters", monsters), ("equipment", equipment)):
        meta = doc.get("_meta") or {}
        if "licence" not in meta or "source" not in meta:
            errors.append(f"{name}: published file is missing its _meta attribution block")

    # A stale manifest is worse than none: clients trust it to decide what NOT to re-download,
    # so a table published without regenerating it would never reach an installed client.
    published = json.loads((ROOT / "data/v1/manifest.json").read_text()).get("files", {})
    actual = manifest.hashes()
    for name in sorted(set(published) | set(actual)):
        if published.get(name) != actual.get(name):
            errors.append(f"manifest: stale for {name} — run tools/manifest.py")

    before = previous_counts()
    counts = json.loads((ROOT / "data/v1/meta.json").read_text())["counts"]
    for key in counts:
        if key == "monstersWithStatOverrides":
            continue  # not a universe count: a parse fixed upstream legitimately removes rows
        check_shrink(errors, key, counts[key], before.get(key))

    if errors:
        print("VALIDATION FAILED:")
        for error in errors:
            print("  -", error)
        sys.exit(1)
    print("validation passed:", counts)


if __name__ == "__main__":
    main()
