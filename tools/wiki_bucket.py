"""Shared OSRS Wiki Bucket API transport for the tools/ generators.

One implementation of the paginated bucket fetch, the combat_style normalisation, and the
infobox_item-to-infobox_bonuses join, so a Bucket API or wiki-quirk fix cannot land in
fetch_data.py's several consumers unevenly.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://oldschool.runescape.wiki/api.php"

ITEM_FIELDS = "'item_name','item_id','page_name','page_name_sub','removal_date'"

# Identical bucket queries within one run answer from here (the item bucket is joined twice).
_memo = {}


def _api_request(query, user_agent):
    """One API call with MediaWiki etiquette: maxlag so the wiki can shed us under load, and
    a bounded backoff on 429/503/maxlag instead of failing the weekly run on a blip."""
    url = API + "?" + urllib.parse.urlencode(
        {"action": "bucket", "format": "json", "query": query, "maxlag": "5"})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=user_agent), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(int(e.headers.get("Retry-After") or 15 * (attempt + 1)))
                continue
            raise
        if data.get("error", {}).get("code") == "maxlag" and attempt < 3:
            time.sleep(15 * (attempt + 1))
            continue
        if "error" in data:
            raise RuntimeError(data["error"])
        return data
    raise RuntimeError("wiki API kept lagging after retries")


def fetch_bucket(query_fields, bucket, user_agent):
    key = (bucket, query_fields)
    if key in _memo:
        return _memo[key]
    rows, offset = [], 0
    while True:
        q = f"bucket('{bucket}').select({query_fields}).limit(5000).offset({offset}).run()"
        batch = _api_request(q, user_agent).get("bucket", [])
        rows.extend(batch)
        if len(batch) < 5000:
            _memo[key] = rows
            return rows
        offset += 5000
        time.sleep(1)


# The wiki's own weapon-category taxonomy (infobox `combat_style`), normalised for the case
# wobble a hand-edited wiki accumulates ('partisan' vs 'Partisan', 'thrown' vs 'Thrown').
# Absent categories normalise to ""
# (falsy, like the raw field), so callers test truthiness rather than None.
def normalise_category(raw):
    if not raw:
        return ""
    return " ".join(w.capitalize() if w != "2h" else "2h" for w in str(raw).strip().split())


def iter_equipment(bonus_fields, user_agent):
    """infobox_item joined to infobox_bonuses on page_name_sub (page_name fallback),
    yielding (bonus_row, item_row, item_ids) with removed items filtered out and the
    non-numeric 'betaNNNN' ids from leagues/beta worlds skipped."""
    items = fetch_bucket(ITEM_FIELDS, "infobox_item", user_agent)
    bonuses = fetch_bucket(bonus_fields, "infobox_bonuses", user_agent)
    by_key = {}
    for r in items:
        by_key.setdefault(r.get("page_name_sub") or r.get("page_name"), []).append(r)
    for b in bonuses:
        for it in by_key.get(b.get("page_name_sub") or b.get("page_name"), []):
            if it.get("removal_date"):
                continue
            ids = []
            for x in (it.get("item_id") or []):
                try:
                    ids.append(int(x))
                except ValueError:
                    pass
            yield b, it, ids
