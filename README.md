# gear-oracle-data

The datasets behind the [Gear Oracle](https://github.com/CrispyLumpsOfSpace/runelite-gear-oracle)
RuneLite plugin, refreshed on a schedule so that plugin installs fetch from here instead of
each hitting the OSRS Wiki's API directly. Data lives apart from code, under the data's own
licences; the plugin repository ships no data at all.

A weekly GitHub Action fetches from the wiki, **validates before publishing** (shape, required
fields, row-count collapse against the previous copy), and commits only what passed — so a
broken wiki edit or an API schema change breaks this pipeline visibly instead of degrading
every installed client. Clients keep serving their last cached copy regardless.

Everything is published as **plain JSON, one row per line in a stable order**, so each refresh
commit is a reviewable row-by-row diff rather than an opaque archive; clients receive it
gzip-compressed on the wire regardless.

The bestiary is **minimised to what the game client cannot answer for itself**: mechanics the
cache has no concept of (attributes, elemental weaknesses, immunities, flat armour, ranged
defence classes, slayer data, attack styles), plus a per-row `ov` block carrying stats only
where the wiki disagrees with the client's cache — multi-phase placeholder ids, per-version
rows sharing one id, and genuine disagreements. Everything else the plugin reads from the
player's own local game cache at runtime. To decide which values need publishing, the pipeline
consults a rendering of that cache (the MOID data files at chisel.weirdgloop.org) transiently
at build time; no cache-derived value is published — the comparison only selects which wiki
values appear, though which fields carry an override is itself a product of it.

## Layout

| Path | Contents | Licence |
|---|---|---|
| `data/v1/monsters.json` | The bestiary, minimised to what the game client's own cache cannot supply | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/equipment.json` | Weapon id → wiki combat category — the one item field the game client has no concept of; names and slots come from the client at runtime | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/meta.json` | Generation date, source, row counts | — |
| `fixtures/v1/` | Test fixtures for the plugin's suite, including the bestiary's full-override variant (tests run without a game client) | [CC BY-NC-SA 3.0](fixtures/LICENSE) |
| `fixtures/v1/scenarios/`, `catalogs/` | Hand-maintained plugin test corpora — CLI smoke scenarios and item catalogs. Authored in the plugin project; stat values transcribed from wiki infoboxes, so they live here with the rest of the wiki-derived data | [CC BY-NC-SA 3.0](fixtures/LICENSE) |
| `fixtures/v1/adversarial-corpus.json` | The mechanic-adversarial corpus. Original test data — its item stats are constructed per scenario, not transcribed | [MIT](tools/LICENSE) |
| `vectors/vectors.json` | Recorded runs of the OSRS Wiki DPS calculator, used to cross-validate the plugin's engine. Dual-provenance: outputs GPL-3.0, resolved stat rows wiki-derived CC BY-NC-SA 3.0 — see [vectors/README.md](vectors/README.md) | [GPL-3.0](vectors/LICENSE) + [CC BY-NC-SA 3.0](data/LICENSE) |

The `v1` path segment is the schema version: a future format change publishes alongside as
`v2`, so released plugin versions keep working.

## Licensing

This repository is data, not code, and each directory carries its own terms:

- Everything under `data/` and `fixtures/` (except the adversarial corpus, below) derives from
  the [Old School RuneScape Wiki](https://oldschool.runescape.wiki/), retrieved through its
  `api.php` Bucket API, and is redistributed under
  [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) — attribution,
  non-commercial and share-alike conditions travel with the files, and the published files
  carry an in-band `_meta` block naming source, licence and retrieval date.
- `fixtures/v1/adversarial-corpus.json` is original authored test data (MIT, `tools/LICENSE`).
- `vectors/vectors.json` records runs of
  [weirdgloop/osrs-dps-calc](https://github.com/weirdgloop/osrs-dps-calc): the computed
  outputs are the calculator's (GPL-3.0), and the resolved monster/item stat rows in each
  scenario reach the recording through the calculator's bundled wiki-derived data files
  (CC BY-NC-SA 3.0) — see `vectors/README.md`. The file's own `source` block records the
  upstream commit and recording date. It exists solely to cross-validate Gear Oracle's
  independently implemented engine.
- The scripts under `tools/` and the workflow are original and MIT-licensed (`tools/LICENSE`).

No game-cache-derived value is published here: facts read from the RuneScape client's own cache
stay on the player's machine. RuneScape and Old School RuneScape are trademarks of Jagex
Limited; this project is not endorsed by or affiliated with Jagex or the OSRS Wiki.
