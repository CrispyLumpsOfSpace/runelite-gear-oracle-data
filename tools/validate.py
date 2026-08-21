#!/usr/bin/env python3
"""Validates a freshly fetched dataset before it is published.

The point of this repo is that a bad wiki edit or a Bucket API schema change breaks THIS
pipeline, visibly, instead of degrading every installed client — so this errs toward failing.
Checks each file's shape, its required fields, that row counts have not collapsed against the
previously published copy (a shrink beyond tolerance means the source query broke), and that
the published manifest still matches the files it hashes.
"""
import json
import subprocess
import sys
from pathlib import Path

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


def main():
    errors = []
    check_tables(errors)
    check_no_source_dumps(errors)

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
        check_shrink(errors, key, counts[key], before.get(key))

    if errors:
        print("VALIDATION FAILED:")
        for error in errors:
            print("  -", error)
        sys.exit(1)
    print("validation passed:", counts)


if __name__ == "__main__":
    main()
