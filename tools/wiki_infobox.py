"""Reads one stat back out of an article's raw {{Infobox Monster}} call.

The Bucket API stores a monster stat only when the infobox parameter is a bare number: a
band ("215-<br />145"), a footnoted number ("40&thinsp;{{CiteTwitter|...}}") and a parameter
left blank all reach a bucket row identically, as an absent field. That collapse is what
made every unparseable stat indistinguishable from a real 0, so the separation has to come
from the article source, which says which of the three it was.

Parameter names follow Template:Infobox Monster; versioned pages suffix each with the
1-based index of the matching `versionN`.
"""
import re

# infobox_monster bucket field -> Template:Infobox Monster parameter.
PARAMETER = {
    "attack_level": "att", "defence_level": "def", "strength_level": "str",
    "ranged_level": "range", "magic_level": "mage",
    "stab_defence_bonus": "dstab", "slash_defence_bonus": "dslash",
    "crush_defence_bonus": "dcrush", "magic_defence_bonus": "dmagic",
    "magic_attack_bonus": "amagic", "range_attack_bonus": "arange",
    "strength_bonus": "strbns", "range_strength_bonus": "rngbns",
    "magic_damage_bonus": "mbns", "size": "size",
}

BLANK = "blank"        # the parameter is absent, empty, or holds only an editor comment
UNPARSED = "unparsed"  # the parameter holds text no rule here turns into one integer


def infobox(wikitext):
    """The {{Infobox Monster}} call, brace-matched so nested templates stay inside it."""
    start = wikitext.find("{{Infobox Monster")
    if start < 0:
        return None
    depth, i = 0, start
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                return wikitext[start:i]
        else:
            i += 1
    return None


def parameters(box):
    """name -> raw value, splitting on the pipes that belong to this template only."""
    values, depth, brackets, current = {}, 0, 0, ""
    parts, i = [], 0
    while i < len(box):
        if box.startswith("{{", i):
            depth += 1
            current += "{{"
            i += 2
        elif box.startswith("}}", i):
            depth -= 1
            current += "}}"
            i += 2
        elif box.startswith("[[", i):
            brackets += 1
            current += "[["
            i += 2
        elif box.startswith("]]", i):
            brackets -= 1
            current += "]]"
            i += 2
        elif box[i] == "|" and depth == 1 and brackets == 0:
            parts.append(current)
            current = ""
            i += 1
        else:
            current += box[i]
            i += 1
    parts.append(current)
    for part in parts[1:]:
        name, sep, value = part.partition("=")
        if sep:
            values[name.strip().lower()] = value.strip()
    return values


def versions(values):
    """The page's version labels in infobox order, so `versionN` maps onto a bucket row."""
    indexed = sorted((int(m.group(1)), values[k])
                     for k in values for m in [re.fullmatch(r"version(\d+)", k)] if m)
    return [label.strip() for _, label in indexed]


_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_STRIPPED = (
    (re.compile(r"(?s)<!--.*?-->"), " "),
    (re.compile(r"(?s)<ref[^>]*>.*?</ref>"), " "),
    (re.compile(r"<[^>]+>"), " "),
    (re.compile(r"&[A-Za-z]+;|&#\d+;"), " "),
)
# A band of two integers: "215-145", "215-<br />145". The wiki writes the fight-start value
# first (Vardorvis' def1 "215-145" descends with its remaining hitpoints), so it is the one
# an en dash or hyphen separates from the end-of-fight value.
_BAND = re.compile(r"([+-]?\d+)\s*[-–—]\s*([+-]?\d+)")


def stat(raw):
    """One integer for an infobox stat, or BLANK / UNPARSED.

    Footnotes and citations are annotation, not value, so they are stripped before parsing.
    A band yields its first-listed value: that is the stat at the start of the fight, the
    only end of the band that is defined while the fight is still running.
    """
    if raw is None:
        return BLANK
    text = raw
    for pattern, replacement in _STRIPPED:
        text = pattern.sub(replacement, text)
    while _TEMPLATE.search(text):
        text = _TEMPLATE.sub(" ", text)
    text = re.sub(r"\s+", " ", text.replace(",", "")).strip()
    if not text:
        return BLANK
    try:
        return int(text)
    except ValueError:
        pass
    band = _BAND.fullmatch(text)
    return int(band.group(1)) if band else UNPARSED


def read(values, field, version_anchor):
    """The wiki's own text for one stat of one version, resolved to an int, BLANK or UNPARSED.

    Returns (value, raw), the raw text kept so a gap report can say what defeated the parse.
    """
    labels = versions(values)
    name = PARAMETER[field]
    if labels:
        anchor = (version_anchor or "").strip().lower()
        matches = [i for i, label in enumerate(labels, 1) if label.lower() == anchor]
        if matches:
            name = f"{name}{matches[0]}"
        elif anchor:
            return UNPARSED, f"<no infobox version matching {version_anchor!r}>"
    raw = values.get(name)
    if raw is None and name != PARAMETER[field]:
        raw = values.get(PARAMETER[field])  # a stat shared by every version is unsuffixed
    return stat(raw), raw
