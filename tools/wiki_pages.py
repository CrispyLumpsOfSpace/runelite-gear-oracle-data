"""Fetches OSRS Wiki page text for quote checking, and matches a quote against it.

Separate from wiki_bucket.py because that speaks action=bucket to the structured infobox
store, while a citation names an article and needs its prose. The etiquette is the same:
maxlag so the wiki can shed us under load, a bounded backoff, and an identifying user agent.

Both renderings of a page are offered because a hand-written citation may have been copied
from either: the rendered article (what a reader sees, with templates expanded) or the raw
wikitext (what {{Template}} calls and [[links]] look like underneath).
"""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://oldschool.runescape.wiki/api.php"
CACHE = Path(__file__).resolve().parent / ".cache" / "wiki-pages"
USER_AGENT = {
    "User-Agent": "gear-oracle-data citation checker "
                  "(https://github.com/CrispyLumpsOfSpace/runelite-gear-oracle-data)"
}


def title_of(url):
    """The article title a wiki URL names, or None when it is not a wiki article URL."""
    if "oldschool.runescape.wiki" not in url or "/w/" not in url:
        return None
    title = urllib.parse.unquote(url.split("/w/", 1)[1])
    return title.split("#")[0].replace("_", " ").strip() or None


def _request(params):
    url = API + "?" + urllib.parse.urlencode(dict(params, format="json", maxlag="5"))
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=USER_AGENT), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(int(e.headers.get("Retry-After") or 15 * (attempt + 1)))
                continue
            raise
        error = data.get("error")
        if isinstance(error, dict) and error.get("code") == "maxlag" and attempt < 3:
            time.sleep(15 * (attempt + 1))
            continue
        if error is not None:
            raise RuntimeError(error)
        return data
    raise RuntimeError("wiki API kept lagging after retries")


def _cached(key, produce):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = produce()
    path.write_text(json.dumps(value), encoding="utf-8")
    return value


def _strip_html(rendered):
    text = re.sub(r"(?s)<(script|style|sup)\b.*?</\1>", " ", rendered)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))


def fetch(title, delay=0.5):
    """{'wikitext', 'rendered', 'missing'} for an article title, memoised on disk.

    Redirects are resolved by the API itself (redirects=1), so a citation naming an old
    title still reads the page it lands on.
    """
    def produce():
        time.sleep(delay)
        page = {"wikitext": "", "rendered": "", "missing": False}
        query = _request({"action": "query", "prop": "revisions", "rvslots": "main",
                          "rvprop": "content", "redirects": "1", "titles": title})
        pages = list(query.get("query", {}).get("pages", {}).values())
        if not pages or "missing" in pages[0]:
            page["missing"] = True
            return page
        revisions = pages[0].get("revisions") or [{}]
        page["wikitext"] = revisions[0].get("slots", {}).get("main", {}).get("*", "")
        try:
            time.sleep(delay)
            parse = _request({"action": "parse", "prop": "text", "redirects": "1",
                              "page": title})
            page["rendered"] = _strip_html(parse.get("parse", {}).get("text", {}).get("*", ""))
        except Exception:
            pass  # The wikitext alone still answers most quotes; a parse failure is not fatal.
        return page
    return _cached("page:" + title, produce)


_PUNCTUATION = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-",
                "—": "-", "−": "-", "×": "x", "≥": ">=", "≤": "<=",
                " ": " ", "​": ""}


def normalise(text):
    """Flatten wiki markup and unify punctuation, so a human-copied quote can match.

    Follows the conventions of the workspace's citecheck.py, which validated the plugin's
    javadoc citations against the same wiki.
    """
    text = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{[Cc]quote2?\|", " ", text)
    text = re.sub(r"(?s)<ref[^>]*>.*?</ref>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("'''", "").replace("''", "")
    for a, b in _PUNCTUATION.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().lower()


def find_quote(page, quote):
    """'wikitext', 'rendered', a 'partial:N' prefix match, or None."""
    needle = normalise(quote)
    if not needle:
        return None
    for name in ("wikitext", "rendered"):
        if needle in normalise(page.get(name) or ""):
            return name
    words = needle.split()
    haystack = normalise(page.get("wikitext", "")) + " " + normalise(page.get("rendered", ""))
    for n in (14, 10, 7):
        if len(words) > n and " ".join(words[:n]) in haystack:
            return "partial:%d" % n
    return None
