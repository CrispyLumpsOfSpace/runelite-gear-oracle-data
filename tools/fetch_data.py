#!/usr/bin/env python3
"""Fetches the published datasets from the OSRS Wiki's Bucket API.

Outputs (all wiki-derived, CC BY-NC-SA 3.0 — see data/LICENSE), each published as PLAIN JSON
with one row per line in a stable sort order, so every weekly refresh is a reviewable diff
rather than an opaque archive. Clients receive them gzip-compressed on the wire regardless
(raw.githubusercontent.com honours Accept-Encoding).

This writer, not tools/format_data.py, is the canonical layout for the files it produces:
one line per row keeps a 1.5MB bestiary reviewable where a fully expanded one would not be.
format_data.py holds the hand-authored tables to their own expanded layout and leaves these
alone.

  data/v1/monsters.json  -- the bestiary, minimised: only what the game client's own cache
      cannot supply. Stats the cache carries (levels, melee/magic defence bonuses, attack-side
      bonuses, size) appear per-row under "ov" ONLY where the wiki disagrees with
      the cache or the cache holds a placeholder — the plugin reads everything else from the
      player's local game cache at runtime. combat_level and hitpoints are always present: they
      key the plugin's version dedupe, and multi-version rows genuinely differ per version on a
      shared cache id.
  data/v1/equipment.json -- weapon id -> wiki combat_style category. Names and slots come from
      the player's own game client at runtime, so the category — the one field the client has
      no concept of — is all this publishes.
  fixtures/v1/monsters-full.json -- the same bestiary with "ov" fully populated for every row,
      for the plugin's test suite, which runs without a game client.
  fixtures/v1/equipment-full.json -- the full pre-joined EquipmentRow shape (name, ids, slot,
      category), likewise for the clientless test suite.
  fixtures/v1/reference-attributes.json        -- monster id -> attribute list (cross-check)
  fixtures/v1/reference-weapon-categories.json -- weapon id -> category/speed/ranged (cross-check)
  fixtures/v1/monster-stat-gaps.json -- every stat the wiki could not state as one number,
      the report tools/validate.py holds the publish against.

To decide which stats need publishing, the pipeline consults a rendering of the game client's
cache (chisel.weirdgloop.org) transiently at build time. No cache-derived value is published or
committed: the comparison only selects WHICH wiki values appear, and every published value is
the wiki's.

Stat parsing policy
-------------------
The Bucket API stores a monster stat only when the infobox parameter is a bare number, so a
band, a footnoted number and a blank parameter all arrive as an absent bucket field. Each is
resolved against the article's own {{Infobox Monster}} source (tools/wiki_infobox.py):

  band ("215-<br />145")     -> the first-listed value, the stat at the start of the fight.
      The other end is reached only at 0 hitpoints, where the fight is over, so it is the
      one end that is defined for the whole encounter. Monsters whose defence scales through
      a kill are therefore published at their opening defence, not averaged over it.
  footnoted ("40&thinsp;{{CiteTwitter|...}}") -> the number; a citation is annotation.
  blank, absent, or anything else (Yama's "-30 ... or +60" conditional) -> unknown: the stat
      is omitted from "ov" entirely, so the plugin fills it from the player's game cache
      rather than being handed a wiki 0 the wiki never claimed.

A stat coerced to 0 here would be published as an override precisely because it disagrees
with the cache, so the parse failure would outrank the correct value.
"""
import datetime
import json
import re
import urllib.request
from pathlib import Path

import wiki_infobox
import wiki_pages
from wiki_bucket import fetch_bucket, iter_equipment, normalise_category

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "gear-oracle-data/1.0 "
      "(https://github.com/CrispyLumpsOfSpace/gear-oracle-data; richardsonjoe321@gmail.com) "
      "scheduled weekly refresh"}
CHISEL_NPCS = "https://chisel.weirdgloop.org/moid/data_files/npcsmin.js"

# This field list owns the bestiary schema: a field added here is what starts flowing to clients.
MONSTER_FIELDS = (
    "'name','page_name','id','combat_level','hitpoints','defence_level','magic_level','magic_attack_bonus',"
    "'stab_defence_bonus','slash_defence_bonus','crush_defence_bonus','magic_defence_bonus','range_defence_bonus',"
    "'light_range_defence_bonus','standard_range_defence_bonus','heavy_range_defence_bonus',"
    "'poison_resistance','venom_resistance','thrall_immune','cannon_immune','burn_immune','freeze_resistance',"
    "'attack_level','strength_level','ranged_level','attack_bonus',"
    "'range_attack_bonus','strength_bonus','range_strength_bonus','magic_damage_bonus',"
    "'attack_speed','attack_style','max_hit',"
    "'slayer_level','slayer_experience','slayer_category',"
    "'is_members_only','default_version','examine','version_anchor',"
    "'elemental_weakness','elemental_weakness_percent','attribute','size','flat_armour'"
)

# Fields the game client's own cache supplies, and where it keeps each: the NPC stats array
# (index) or an NPC param (id). Established against live clients on both world types — see the
# plugin repository's data-source migration. Everything else the plugin needs is wiki-only.
CACHE_STAT_INDEX = {
    "attack_level": 0, "defence_level": 1, "strength_level": 2, "ranged_level": 4, "magic_level": 5,
}
CACHE_PARAM = {
    "stab_defence_bonus": "5", "slash_defence_bonus": "6", "crush_defence_bonus": "7",
    "magic_defence_bonus": "8", "magic_attack_bonus": "3", "range_attack_bonus": "4",
    "strength_bonus": "10", "range_strength_bonus": "12", "magic_damage_bonus": "65",
}
CACHE_FIELDS = list(CACHE_STAT_INDEX) + list(CACHE_PARAM) + ["size"]

# Everything else the plugin consumes travels in full on every row.
KEPT_FIELDS = [
    "name", "page_name", "id", "version_anchor", "default_version", "is_members_only",
    "combat_level", "hitpoints",
    "attack_style", "max_hit", "attack_bonus", "attack_speed", "examine",
    "slayer_level", "slayer_experience", "slayer_category",
    "attribute", "elemental_weakness", "elemental_weakness_percent",
    "poison_resistance", "venom_resistance", "thrall_immune", "cannon_immune", "burn_immune",
    "freeze_resistance", "flat_armour",
    "range_defence_bonus", "light_range_defence_bonus", "standard_range_defence_bonus",
    "heavy_range_defence_bonus",
]


def dataset_meta():
    """In-band CC BY-NC-SA attribution: these files are fetched one at a time from raw
    hosting, so a notice that only lives in the README never reaches the consumer."""
    return {
        "source": "Old School RuneScape Wiki (https://oldschool.runescape.wiki), Bucket API",
        "licence": "CC BY-NC-SA 3.0 (https://creativecommons.org/licenses/by-nc-sa/3.0/)"
                   " — see data/LICENSE",
        "retrieved": datetime.date.today().isoformat(),
    }


def write_rows(path, rows, meta=None):
    """One row per line, so refresh commits diff row-by-row in the GitHub UI."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("{")
        if meta is not None:
            f.write('"_meta":' + json.dumps(meta, separators=(",", ":")) + ",\n")
        f.write('"rows":[\n')
        f.write(",\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in rows))
        f.write("\n]}\n")


def load_cache_npcs():
    text = urllib.request.urlopen(
        urllib.request.Request(CHISEL_NPCS, headers=UA), timeout=180).read().decode("utf-8")
    npcs = json.loads(text[text.index("["):text.rindex("]") + 1])
    return {n["id"]: n for n in npcs}


def cache_effective(npc, field):
    """What the game client would answer for this field; None when the cache cannot say."""
    if npc is None:
        return None
    if field == "size":
        return npc.get("size", 1)
    if field in CACHE_STAT_INDEX:
        stats = npc.get("stats")
        if not stats or len(stats) < 6 or stats == [1, 1, 1, 1, 1, 1]:
            return None  # absent or a multi-phase placeholder: the cache cannot say
        return stats[CACHE_STAT_INDEX[field]]
    return (npc.get("params") or {}).get(CACHE_PARAM[field], 0)


UNKNOWN = "unknown"  # no int the wiki states; distinct from every value wiki_int can return


def wiki_int(row, field):
    """The wiki's integer for one stat, or UNKNOWN when the bucket row does not hold one.

    UNKNOWN covers a blank parameter and one the Bucket API dropped alike; recover_stats()
    separates them from the article source. See the module docstring for why neither may
    become a 0.
    """
    value = row.get(field)
    try:
        return int(value)
    except (TypeError, ValueError):
        return UNKNOWN


def recover_stats(rows):
    """Second pass over the articles whose bucket row is missing a stat.

    Returns (recovered, gaps): {(page_name, version_anchor, field): int} for the stats the
    infobox does state, and a gap row per stat it does not, for the report validate.py holds
    the publish against.
    """
    wanted = {}
    for row in rows:
        missing = [f for f in CACHE_FIELDS if wiki_int(row, f) is UNKNOWN]
        if missing:
            wanted.setdefault(row.get("page_name") or "", []).append((row, missing))

    recovered, gaps = {}, []
    for title, entries in sorted(wanted.items()):
        box = wiki_infobox.infobox(wiki_pages.wikitext(title, delay=0.2) or "")
        values = wiki_infobox.parameters(box) if box else {}
        for row, missing in entries:
            anchor = row.get("version_anchor") or ""
            for field in missing:
                value, raw = (wiki_infobox.read(values, field, anchor) if values
                              else (wiki_infobox.BLANK, None))
                if isinstance(value, int):
                    recovered[(title, anchor, field)] = value
                else:
                    gap = {"page_name": title, "version_anchor": anchor, "field": field,
                           "why": value}
                    if raw:
                        gap["raw"] = raw  # what defeated the parse; a blank parameter has none
                    gaps.append(gap)
    return recovered, gaps


def primary_id(row):
    for i in row.get("id") or []:
        try:
            return int(i)
        except ValueError:
            continue
    return None


_MARKUP = re.compile(r"<[A-Za-z/!]")


def clean(value):
    """A failed wiki template renders inline HTML (an ERR span) where a value should be; that
    is wiki markup, not data, so the field is dropped rather than republished."""
    if isinstance(value, str) and _MARKUP.search(value):
        return None
    if isinstance(value, list):
        kept = [v for v in (clean(x) for x in value) if v is not None]
        return kept or None
    return value


def fetch_monsters(cache_npcs):
    rows = fetch_bucket(MONSTER_FIELDS, "infobox_monster", UA)
    if not rows:
        raise SystemExit("monster fetch returned no rows")

    recovered, gaps = recover_stats(rows)

    minimal, full = [], []
    for row in rows:
        base = {f: clean(row[f]) for f in KEPT_FIELDS if f in row and clean(row[f]) is not None}
        npc = cache_npcs.get(primary_id(row))
        overrides, everything = {}, {}
        for field in CACHE_FIELDS:
            wiki_value = wiki_int(row, field)
            if wiki_value is UNKNOWN:
                wiki_value = recovered.get(
                    (row.get("page_name") or "", row.get("version_anchor") or "", field), UNKNOWN)
            if wiki_value is UNKNOWN:
                continue  # the wiki does not state it; the game cache answers instead
            everything[field] = wiki_value
            if cache_effective(npc, field) != wiki_value:
                overrides[field] = wiki_value
        minimal.append({**base, "ov": overrides} if overrides else base)
        full.append({**base, "ov": everything})

    def sort_key(r):
        ids = r.get("id") or ["0"]
        return (int(ids[0]) if str(ids[0]).isdigit() else 0,
                r.get("version_anchor") or "", r.get("name") or "")
    minimal.sort(key=sort_key)
    full.sort(key=sort_key)

    overridden = sum(1 for r in minimal if "ov" in r)
    write_rows(ROOT / "data/v1/monsters.json", minimal, meta=dataset_meta())
    write_rows(ROOT / "fixtures/v1/monsters-full.json", full, meta=dataset_meta())
    gaps.sort(key=lambda g: (g["page_name"], g["version_anchor"], g["field"]))
    write_rows(ROOT / "fixtures/v1/monster-stat-gaps.json", gaps, meta={
        "comment": "Stats no published row may carry: the wiki states no single number for "
                   "them. validate.py fails the publish if one appears in an 'ov' block, "
                   "which is how a silently zeroed stat would reach clients. "
                   "Generated by tools/fetch_data.py; do not hand-edit.",
        "retrieved": datetime.date.today().isoformat(),
    })
    return len(minimal), overridden, len(gaps)


def fetch_equipment():
    rows = []
    for b, it, ids in iter_equipment(
            "'page_name','page_name_sub','equipment_slot','combat_style'", UA):
        if ids:
            rows.append({"name": it.get("item_name") or "", "ids": ids,
                         "slot": b.get("equipment_slot"),
                         "category": normalise_category(b.get("combat_style"))})
    if not rows:
        raise SystemExit("equipment fetch returned no rows")
    rows.sort(key=lambda r: (r["ids"][0], r["name"]))

    # The published runtime file is only what the client cannot answer: the wiki's editorial
    # weapon category, per id. One entry per line so refreshes diff row-by-row.
    categories = {}
    for r in rows:
        if r.get("category") and r.get("slot") in ("weapon", "2h"):
            for i in r["ids"]:
                categories[i] = r["category"]
    with open(ROOT / "data/v1/equipment.json", "w", encoding="utf-8") as f:
        f.write('{"_meta":' + json.dumps(dataset_meta(), separators=(",", ":")) + ",\n")
        f.write('"categories":{\n')
        f.write(",\n".join(f'"{i}":{json.dumps(categories[i], ensure_ascii=False)}'
                            for i in sorted(categories)))
        f.write("\n}}\n")

    # The clientless test suite still needs the full joined rows.
    with open(ROOT / "fixtures/v1/equipment-full.json", "w", encoding="utf-8") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) for r in rows))
        f.write("\n]\n")
    return len(categories), len(rows)


# The wiki attribute tokens the plugin models, mapped onto MonsterAttribute names. Anything
# absent here is deliberately unmodelled, and the attribute test only compares attributes both
# sides claim to carry.
MAPPED = {
    "undead": "UNDEAD",
    "dragon": "DRAGON",
    "demon": "DEMON",
    "kalphite": "KALPHITE",
    "leafy": "LEAFY",
    "vampyre1": "VAMPYRE_1",
    "vampyre2": "VAMPYRE_2",
    "vampyre3": "VAMPYRE_3",
    "golem": "GOLEM",
    "fiery": "FIERY",
    "rat": "RAT",
    "flying": "FLYING",
    "shade": "SHADE",
}

WEAPON_SLOTS = {"weapon", "2h"}


def version_of(row):
    sub = row.get("page_name_sub") or ""
    return sub.split("#", 1)[1] if "#" in sub else ""


def fetch_reference_fixtures():
    today = datetime.date.today().isoformat()

    rows = fetch_bucket("'page_name','page_name_sub','id','attribute'", "infobox_monster", UA)
    by_id = {}
    for row in rows:
        mapped = sorted({MAPPED[a] for a in (row.get("attribute") or []) if a in MAPPED})
        for raw_id in row.get("id") or []:
            try:
                monster_id = int(raw_id)
            except ValueError:
                continue
            # Union across duplicate rows for the same id (re-listed versions).
            merged = sorted(set(by_id.get(str(monster_id), [])) | set(mapped))
            by_id[str(monster_id)] = merged
    (ROOT / "fixtures/v1/reference-attributes.json").write_text(json.dumps({
        "_comment": "Generated from the OSRS Wiki's infobox_monster bucket (the `attribute` "
                    "field). Do not hand-edit.",
        "_retrieved": today,
        "attributesById": dict(sorted(by_id.items())),
    }, indent=1) + "\n", encoding="utf-8")

    weapons, seen_ids = [], set()
    for b, it, ids in iter_equipment(
            "'page_name','page_name_sub','equipment_slot','combat_style',"
            "'weapon_attack_speed','range_attack_bonus'", UA):
        if (b.get("equipment_slot") or "").lower() not in WEAPON_SLOTS:
            continue
        for item_id in ids:
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            weapons.append({
                "id": item_id,
                "name": it.get("item_name") or "",
                "version": version_of(b),
                "category": normalise_category(b.get("combat_style")),
                "rangedAttack": int(b.get("range_attack_bonus") or 0),
                "speed": int(b.get("weapon_attack_speed") or 0),
            })
    weapons.sort(key=lambda w: w["id"])
    (ROOT / "fixtures/v1/reference-weapon-categories.json").write_text(json.dumps({
        "_meta": {
            "source": "OSRS Wiki Bucket API: infobox_item joined to infobox_bonuses "
                      "(combat_style, weapon_attack_speed, range_attack_bonus)",
            "retrieved": today,
            "purpose": "Cross-reference for WeaponClassificationCrossCheckTest and "
                       "AttackSpeedCrossCheckTest: category and speed are DATA here, where "
                       "the plugin derives or hardcodes.",
        },
        "weapons": weapons,
    }, separators=(",", ":")) + "\n", encoding="utf-8")
    return len(by_id), len(weapons)


def main():
    cache_npcs = load_cache_npcs()
    monsters, overridden, gaps = fetch_monsters(cache_npcs)
    equipment, equipmentRows = fetch_equipment()
    attributes, weapons = fetch_reference_fixtures()
    (ROOT / "data/v1/meta.json").write_text(json.dumps({
        "generated": datetime.date.today().isoformat(),
        "source": "OSRS Wiki Bucket API (oldschool.runescape.wiki/api.php)",
        "licence": "CC BY-NC-SA 3.0 — see data/LICENSE",
        "counts": {"monsters": monsters, "monstersWithStatOverrides": overridden,
                   "equipmentCategories": equipment, "equipmentRows": equipmentRows,
                   "referenceAttributes": attributes, "referenceWeapons": weapons},
    }, indent=1) + "\n")
    print(f"monsters={monsters} (ov={overridden}, statGaps={gaps}) categories={equipment} "
          f"rows={equipmentRows} attributes={attributes} weapons={weapons}")


if __name__ == "__main__":
    main()
