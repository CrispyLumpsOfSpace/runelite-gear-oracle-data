# gear-oracle-data

The datasets behind the [Gear Oracle](https://github.com/CrispyLumpsOfSpace/runelite-gear-oracle)
RuneLite plugin, refreshed on a schedule so that plugin installs fetch from here instead of
each hitting the OSRS Wiki's API directly. Data lives apart from code, under the data's own
licences; the plugin repository ships none of these tables, keeping only two small built-in
fallbacks of its own.

The split is what lets the plugin's modelling move quickly and safely. Because the mechanic
rows and combat tables are published here, a newly modelled mechanic or a corrected
calculation reaches players on this repository's cadence — the day the content lands — under
the validation ladder the pipeline and the plugin's test suite enforce, with no plugin release
or Plugin Hub review in its path. It also keeps policy (which mechanics exist and what numbers
they carry) out of the plugin, leaving it only the engine that evaluates them: modelling more
mechanics costs zero tokens against the Hub's 200k-token review cap on the jar.

A weekly GitHub Action fetches from the wiki, **validates before publishing** (shape, required
fields, row-count collapse against the previous copy), and commits only what passed — so a
broken wiki edit or an API schema change breaks this pipeline visibly instead of degrading
every installed client. Clients keep serving their last cached copy regardless.

## Branches

Clients read `master`; the weekly refresh lands on `staging`. CI force-pushes each refresh to
`staging` as a single snapshot commit on top of `master` and opens a promotion pull request —
merging it is what serves the refresh to clients. To test staged data first, launch the plugin
with `GEAR_ORACLE_DATA_BRANCH=staging` in its environment.

Every push and pull request runs `.github/workflows/validate.yml`: `tools/validate.py` over the
committed tree, then the plugin's own test suite against that tree rather than against the
commit its `wikiDataPin` names (`./gradlew test -PwikiDataSource=<this checkout>`). Hand-edited
tables merge to `master` unreviewed by the refresh pipeline, and clients read `master`.

Everything is published as **plain JSON in a stable order**, so each refresh commit is a
reviewable diff rather than an opaque archive: the pipeline-fetched files and the simpler hand
tables put one row per line, and the hand-authored tables whose rows carry conditions and
expressions are pretty-printed so a row's own fields diff line by line. Clients receive it
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
| `data/v1/mechanic-{weapons,gear,monsters,immunities}.json` | The engine's mechanic rows themselves, named apart from the bestiary's `monsters.json`. The plugin resolves these by id as it builds, so an absent copy leaves it with no mechanics until the fetch lands | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/mechanic-rows.json` | Additive mechanic rows, served to the plugin's row grammar: these extend the four `mechanic-*` files above rather than replacing any of them | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/{monster-families,weapon-families,damage-caps,equipment-sets,magic-base-hits,special-attack-weapons,potions,prayers}.json` | The overlay-served combat tables. The plugin bundles no copy of any of them, so the file published here is the table: it installs whole as the fetch lands, replacing whatever the last one left, and the plugin's table answers empty until then | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/{status-immunities,slayer-finishers,slayer-equipment}.json` | Monster status immunities, Slayer finishing items, Slayer equipment requirements | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/{always-max-hit-targets,required-weapon-immunities}.json` | Per-monster-id combat rules: guaranteed max hits, weapons a kill requires. Style immunities are ordinary rows of `mechanic-immunities.json` | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/level-requirements.json` | Item level requirements for the ids the game cache's own item parameters cannot spell out | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/combat-spells.json` | Every castable spell: book, element, max hit, level and rune cost. A row here adds a spell the picker can choose, with no plugin release | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/{combat-options,runes,darts}.json` | The game's Combat Options table per weapon category, rune item ids with their names, and dart ids by the name the blowpipe's Check message spells | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/encounter-gear.json` | Per-encounter gear availability: which slots survive an arena that confiscates equipment, and which items it supplies that no bank can hold | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/special-item-patterns.json` | Name patterns that classify an item into the engine's special-weapon taxonomy | [CC BY-NC-SA 3.0](data/LICENSE) |
| `data/v1/{setup-copy,setup-modifiers,setup-drains}.json` | The plugin's own UI labels, modifier list, and the spec-drain spinners with the items they belong to. Original authored content, not wiki-derived | [MIT](tools/LICENSE) |
| `data/v1/manifest.json` | Content hash of every runtime file. Clients fetch this one file per startup and re-download only the entries whose hash moved; regenerate with `tools/manifest.py` after any hand-publish | — |
| `data/v1/meta.json` | Generation date, source, row counts | — |
| `fixtures/v1/` | Test fixtures for the plugin's suite, including the bestiary's full-override variant (tests run without a game client) | [CC BY-NC-SA 3.0](fixtures/LICENSE) |
| `fixtures/v1/scenarios/`, `catalogs/` | Hand-maintained plugin test corpora — CLI smoke scenarios and item catalogs. Authored in the plugin project; stat values transcribed from wiki infoboxes, so they live here with the rest of the wiki-derived data | [CC BY-NC-SA 3.0](fixtures/LICENSE) |
| `fixtures/v1/monster-stat-gaps.json` | Every monster stat the wiki states no single number for, so `tools/validate.py` can fail a publish that carries one anyway. Not a client file | [CC BY-NC-SA 3.0](fixtures/LICENSE) |
| `fixtures/v1/adversarial-corpus.json` | The mechanic-adversarial corpus. Original test data — its item stats are constructed per scenario, not transcribed | [MIT](tools/LICENSE) |
| `vectors/vectors.json` | Recorded runs of the OSRS Wiki DPS calculator, used to cross-validate the plugin's engine. Dual-provenance: outputs GPL-3.0, resolved stat rows wiki-derived CC BY-NC-SA 3.0 — see [vectors/README.md](vectors/README.md) | [GPL-3.0](vectors/LICENSE) + [CC BY-NC-SA 3.0](data/LICENSE) |

The `v1` path segment is the schema version: a future format change publishes alongside as
`v2`, so released plugin versions keep working.

## Citations

Every hand-authored row carries a `description`, and rows whose description names something
checkable also carry a `_cite` block beside it. The two are one statement in two halves:

- **`description`** is the field of record and is never rewritten by a tool. It is the prose
  the author wrote: what the row models, the citation as a human reads it, and the row's
  **scope exclusions** — what the row deliberately does *not* model and why. A row cannot
  carry a comment, so that reasoning has nowhere else to live, and none of it is
  machine-checkable.
- **`_cite`** is the machine-checkable half, derived from that prose by
  `tools/migrate_sources.py`: the URLs and the verbatim quotes, so a tool can hold them against
  the live wiki. It adds nothing the `description` does not already say.

The `_` prefix is the data repository's extension point: the plugin's row binder and its
mechanic-row grammar both skip a `_`-prefixed key, so a block like this can be added to a row
shape a released client already reads without that client dropping the row.

```json
{
 "key": "pickaxe",
 "nameContains": ["pickaxe"],
 "description": "https://oldschool.runescape.wiki/w/Slagilith \"will reduce your damage by 67% if a pickaxe is not equipped\"",
 "_cite": [
  {"kind": "wiki", "url": "https://oldschool.runescape.wiki/w/Slagilith", "quotes": ["will reduce your damage by 67% if a pickaxe is not equipped"], "verified": "2026-08-21"}
 ]
}
```

`_cite` is a non-empty list of citations, each one source with everything this row quotes from
it:

| Field | Meaning |
|---|---|
| `kind` | `wiki` (an OSRS Wiki article — the only kind a tool can check), `tweet` (a JMod statement), `sheet` (Bitterkoekje's or another published community sheet), `web` (anything else linked), `unsourced` (the prose quotes a source it never linked), `none` (the row's `CITATION-NONE` marker: a value no source supports, standing until it is reconciled) |
| `url` | The source, `https://` and canonical — for `kind: wiki`, an `https://oldschool.runescape.wiki/w/...` article URL. Absent, and only absent, on `unsourced` and `none` |
| `quotes` | Minimal verbatim spans from that source, in the order the prose quotes them. Empty when the row cites an article without quoting it; never a paraphrase |
| `verified` | ISO date the quotes were last held against the source. Written by `tools/verify_sources.py --update-dates`, and only for a citation whose every quote matched |

### Checking them

`tools/validate.py` checks the **shape** of every `_cite` — kinds, ISO dates, well-formed URLs,
quotes present as strings — with no network, and **blocks**: a malformed block fails CI.

`tools/verify_sources.py` checks the **content**, against the live wiki, and only **reports**.
A wiki article can be reworded the day after it was cited without the fact it stated changing,
so a quote that stops matching is a prompt to go and look, never a reason to block a publish.
That makes it a manual step:

```
tools/verify_sources.py                 # report VERIFIED / PARTIAL / NOT-FOUND / MANUAL
tools/verify_sources.py --limit 40 data/v1/weapon-families.json     # sample one table
tools/verify_sources.py --update-dates  # after eyeballing, stamp today on what matched
tools/verify_sources.py --derive-urls   # propose the article an `unsourced` quote came from
```

Quotes are matched after normalising whitespace, wiki markup and quote punctuation, against
both the rendered article and the raw wikitext, since a citation may have been copied from
either. Non-wiki sources are reported `MANUAL` rather than fetched. `--derive-urls` writes a
URL in only when the candidate page actually contains the quote, so it can promote an
`unsourced` citation but can never invent one. Pages are cached under `tools/.cache/`, so a
rerun after an edit costs nothing.

Re-run `tools/manifest.py` after any of these rewrite a table.

## Formatting

Every hand-authored `data/v1` table is stored in one canonical layout: `indent=1`, every object
and array member on its own line, key order as authored, UTF-8, trailing newline. `_cite`
blocks and deep option lists make a table's rows too long to share lines legibly, and one
layout keeps a row's diff to that row.

```
tools/format_data.py            # rewrite every hand-authored table
tools/format_data.py --check    # name what would change, write nothing
```

`tools/validate.py` runs the same check and **blocks**, so a table cannot be published in a
layout the next tool run would reflow.

The pipeline-written files own their own form instead — expanding the 1.5MB compact bestiary to
one line per field would multiply it — so `tools/fetch_data.py` and `tools/manifest.py` are
canonical for `monsters.json`, `equipment.json`, `meta.json` and `manifest.json`. `vectors/` is
not formatted at all. Re-run `tools/manifest.py` after reformatting: the hashes move.

## Licensing

This repository is data, not code, and each directory carries its own terms:

- Everything under `data/` and `fixtures/` (except the adversarial corpus, below) derives from
  the [Old School RuneScape Wiki](https://oldschool.runescape.wiki/), retrieved through its
  `api.php` Bucket API, and is redistributed under
  [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) — attribution,
  non-commercial and share-alike conditions travel with the files, and the published files
  (monsters.json and equipment.json) carry an in-band `_meta` block naming source, licence and retrieval date.
- `fixtures/v1/adversarial-corpus.json` is original authored test data (MIT, `tools/LICENSE`).
- `vectors/vectors.json` records runs of
  [weirdgloop/osrs-dps-calc](https://github.com/weirdgloop/osrs-dps-calc): the computed
  outputs are the calculator's (GPL-3.0), and the resolved monster/item stat rows in each
  scenario reach the recording through the calculator's bundled wiki-derived data files
  (CC BY-NC-SA 3.0) — see `vectors/README.md`. The file's own `source` block records the
  recording date; its `commit` field is a placeholder (`unknown (reused recording)`), so the
  calculator revision behind these numbers is not pinned — see `vectors/README.md`. It exists solely to cross-validate Gear Oracle's
  independently implemented engine.
- The scripts under `tools/` and the workflow are original and MIT-licensed (`tools/LICENSE`).

No game-cache-derived value is published here: facts read from the RuneScape client's own cache
stay on the player's machine. RuneScape and Old School RuneScape are trademarks of Jagex
Limited; this project is not endorsed by or affiliated with Jagex or the OSRS Wiki.
