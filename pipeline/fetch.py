"""Step 1 - collect headlines from RSS feeds and Google News searches.

Only headline, short summary, link, publisher and date are stored (never full
article text).
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import urllib.parse
import xml.etree.ElementTree as ET

from common import (DATA, http_get, load_json, log, mentions, norm, now_iso,
                    save_json, strip_html)

NEWS = DATA / "news.json"
ATOM = "{http://www.w3.org/2005/Atom}"
# Social-media posts are not independent sources, and bare URLs are not publisher names.
SOCIAL = {"facebook", "instagram", "youtube", "tiktok", "x", "twitter", "reddit", "threads", "linkedin"}


def is_source(publisher: str) -> bool:
    p = (publisher or "").strip().lower()
    return bool(p) and p not in SOCIAL and not p.startswith(("http://", "https://"))


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return email.utils.parsedate_to_datetime(raw).date().isoformat()
    except Exception:  # noqa: BLE001
        pass
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def parse_feed(xml_bytes: bytes, default_publisher: str, google: bool = False) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    entries = root.findall(".//item") + root.findall(f".//{ATOM}entry")
    for e in entries:
        title = strip_html((e.findtext("title") or e.findtext(f"{ATOM}title") or ""))
        link = (e.findtext("link") or "").strip()
        if not link:
            le = e.find(f"{ATOM}link")
            link = le.get("href", "") if le is not None else ""
        pub = default_publisher
        src = e.find("source")
        if src is not None and (src.text or "").strip():
            pub = src.text.strip()
        if google and pub and title.endswith(" - " + pub):
            title = title[: -len(pub) - 3].rstrip()
        summary = ""
        if not google:  # Google News "descriptions" only repeat the headline
            summary = strip_html(e.findtext("description") or e.findtext(f"{ATOM}summary") or "")[:400]
        date = _date(e.findtext("pubDate") or e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published"))
        if title and link.startswith("http"):
            out.append({"title": title, "summary": summary, "url": link, "publisher": pub, "published": date})
    return out


def google_url(query: str, window: str, cfg: dict) -> str:
    q = urllib.parse.quote(f"{query} when:{window}")
    return f"https://news.google.com/rss/search?q={q}&hl={cfg['hl']}&gl={cfg['gl']}&ceid={cfg['ceid']}"


def search_window(store: dict, g: dict) -> str:
    """How far back to ask Google News: since the last run (+3 days of overlap), at least `window`, at most 30d."""
    if not store["items"] or not store.get("updated"):
        return g["first_run_window"]
    try:
        days = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(store["updated"])).days
    except ValueError:
        return g["window"]
    return f"{min(max(days + 3, int(g['window'].rstrip('d'))), 30)}d"


def run() -> dict:
    sources = load_json(DATA / "sources.json")
    politicians = load_json(DATA / "politicians.json")
    store = load_json(NEWS, {"updated": None, "items": []})
    g = sources["google_news"]
    window = search_window(store, g)

    jobs: list[tuple[str, str, bool]] = [(f["url"], f["name"], False) for f in sources["feeds"]]
    queries = [q for p in politicians for q in p["news_queries"]] + g["topic_queries"]
    jobs += [(google_url(q, window, g), "Google News", True) for q in queries]

    known = {i["id"]: i for i in store["items"]}
    added = 0
    for url, name, is_google in jobs:
        try:
            items = parse_feed(http_get(url), name, google=is_google)
        except Exception as e:  # noqa: BLE001
            log(f"  feed failed ({name}): {type(e).__name__}: {e}")
            continue
        for it in items:
            if not is_source(it["publisher"]):
                continue
            iid =hashlib.sha1(norm(it["title"]).encode("utf-8")).hexdigest()[:12]
            if iid in known:
                continue
            text = f"{it['title']} {it['summary']}"
            it["id"] = iid
            it["politicians"] = [p["id"] for p in politicians if mentions(text, p["aliases"])]
            it["fetched"] = now_iso()
            known[iid] = it
            added += 1

    cutoff = (dt.date.today() - dt.timedelta(days=sources["limits"]["keep_news_days"])).isoformat()
    items = [i for i in known.values() if (i.get("published") or "9999") >= cutoff and is_source(i["publisher"])]
    items.sort(key=lambda i: i.get("published") or "", reverse=True)
    items = items[: sources["limits"]["max_news_items"]]
    save_json(NEWS, {"updated": now_iso(), "items": items})
    log(f"fetch: {len(jobs)} sources, {added} new headlines, {len(items)} kept")
    return {"added": added, "total": len(items)}


if __name__ == "__main__":
    run()
