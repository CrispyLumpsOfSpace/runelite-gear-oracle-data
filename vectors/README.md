# vectors

`vectors.json` records runs of the OSRS Wiki's DPS calculator,
[weirdgloop/osrs-dps-calc](https://github.com/weirdgloop/osrs-dps-calc), licensed
**GPL-3.0** (see LICENSE). The scenarios are Gear Oracle's own
(`tools/wiki-oracle/authored-scenarios.test.ts` in the plugin repository), executed against the
calculator as a black box. The file's `source` block records the upstream commit and the
recording date.

Each vector carries two kinds of upstream content, under two sets of terms:

- the **computed outputs** (max hits, attack/defence rolls, DPS) are the calculator's, and
  travel under its **GPL-3.0**;
- the **fully-resolved monster and item stat rows** in each scenario are resolved by the
  calculator from its bundled data files, which derive from the
  [Old School RuneScape Wiki](https://oldschool.runescape.wiki/) — those values travel under
  [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) (legal code in
  `../data/LICENSE`), reaching this recording through the calculator.

The file is dual-provenance: reuse of the outputs is a GPL question, reuse of the stat rows is
a wiki-data question, and redistribution of the file as a whole must satisfy both. No code,
schema, or test-case text from the calculator is included; the vector vocabulary is Gear
Oracle's own.

It exists solely to cross-validate Gear Oracle's independently implemented DPS engine
(`WikiReferenceTest`); the engine contains no code from that project.
