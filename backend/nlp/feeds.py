"""
nlp/feeds.py
============
Direct outlet feeds that complement Google News for the most recent days:

* RSS feeds of Indian business outlets (Business Standard, Economic Times,
  Livemint, Hindu BusinessLine, CNBC-TV18, NDTV Profit, Times of India,
  Indian Express) — see config.RSS_FEEDS
* Moneycontrol's official Google-News sitemap (its RSS feeds stopped
  updating in 2024)

These feeds only carry the latest few dozen stories each, so they add
coverage for live scoring but cannot reach back in time; Google News
(nlp/news.py) provides the history. Every article is tagged with a
normalised outlet name so the dashboard can compare sources.

Fetched with an honest, self-identifying feed-reader User-Agent: some
publishers reject anonymous library defaults.
"""

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from config import CACHE_DIR, FEED_LOOKBACK_HOURS, RSS_FEEDS

logger = logging.getLogger(__name__)

FEED_HEADERS = {
    "User-Agent": "BrandRiskMonitor/2.0 (RSS feed reader; academic research project)",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
}
MONEYCONTROL_SITEMAP = "https://www.moneycontrol.com/news/news-sitemap.xml"
_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "n": "http://www.google.com/schemas/sitemap-news/0.9"}
POOL_CACHE = CACHE_DIR / "news" / "_outlet_feeds.json"
IST = timezone(timedelta(hours=5, minutes=30))

# Map publisher names seen in feeds / Google News onto one outlet name
_OUTLET_ALIASES = [
    (r"economictimes|economic times|^et now|^etnow|^et ", "Economic Times"),
    (r"business[- ]?standard", "Business Standard"),
    (r"moneycontrol", "Moneycontrol"),
    (r"livemint|^mint$|^mint ", "Livemint"),
    (r"businessline|business line", "Hindu BusinessLine"),
    (r"^the hindu$|thehindu\.com", "The Hindu"),
    (r"cnbc[- ]?tv ?18|cnbctv18", "CNBC-TV18"),
    (r"ndtv ?profit|ndtvprofit", "NDTV Profit"),
    (r"times of india|timesofindia", "Times of India"),
    (r"indian express|indianexpress", "Indian Express"),
    (r"financial express|financialexpress", "Financial Express"),
    (r"zee ?business|zeebiz", "Zee Business"),
    (r"reuters", "Reuters"),
    (r"bloomberg", "Bloomberg"),
]

# Last per-outlet article counts (shown by /api/live/status)
INGEST_STATS: dict[str, int] = {}


def normalize_outlet(name: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    for pattern, outlet in _OUTLET_ALIASES:
        if re.search(pattern, low):
            return outlet
    n = re.sub(r"^www\.", "", n, flags=re.I)
    return re.sub(r"\.(com|in|co\.in)$", "", n) or "Unknown"


def clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(html.unescape(text))          # some feeds double-encode (&amp;amp;)
    return re.sub(r"\s+", " ", text).strip()


def _article(title, published, outlet, url, provider):
    return {"title": title, "source": outlet, "url": url, "provider": provider,
            "published": published.isoformat(), "date": published.astimezone(IST).date().isoformat()}


def _rss(outlet: str, url: str, cutoff: datetime) -> list[dict]:
    out = []
    try:
        r = requests.get(url, headers=FEED_HEADERS, timeout=15)
        if r.status_code != 200:
            logger.debug("Feed %s returned HTTP %s", url, r.status_code)
            return out
        for it in ET.fromstring(r.content).iter("item"):
            title = clean_text(it.findtext("title") or "")
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
            except Exception:
                continue
            if title and pub >= cutoff:
                out.append(_article(title, pub, outlet, it.findtext("link") or "", "rss"))
    except Exception as exc:
        logger.debug("Feed %s failed: %s", url, exc)
    return out


def _moneycontrol(cutoff: datetime) -> list[dict]:
    out = []
    try:
        r = requests.get(MONEYCONTROL_SITEMAP, headers=FEED_HEADERS, timeout=20)
        r.raise_for_status()
        for u in ET.fromstring(r.content).findall("s:url", _NS):
            title = clean_text(u.findtext("n:news/n:title", default="", namespaces=_NS))
            try:
                pub = datetime.fromisoformat(u.findtext("n:news/n:publication_date", default="", namespaces=_NS))
                pub = pub.astimezone(timezone.utc)
            except ValueError:
                continue
            if title and pub >= cutoff:
                out.append(_article(title, pub, "Moneycontrol", u.findtext("s:loc", default="", namespaces=_NS), "moneycontrol"))
    except Exception as exc:
        logger.warning("Moneycontrol sitemap failed: %s", exc)
    return out


def fetch_outlet_feeds(offline: bool = False, lookback_hours: int = FEED_LOOKBACK_HOURS) -> list[dict]:
    """All recent articles from the configured outlets (not yet filtered by company)."""
    if offline:
        return json.loads(POOL_CACHE.read_text(encoding="utf-8")) if POOL_CACHE.exists() else []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    jobs = [(outlet, url) for outlet, urls in RSS_FEEDS.items() for url in urls]
    pool, per_outlet = [], {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (outlet, _), batch in zip(jobs, ex.map(lambda j: _rss(j[0], j[1], cutoff), jobs)):
            pool.extend(batch)
            per_outlet[outlet] = per_outlet.get(outlet, 0) + len(batch)
    mc = _moneycontrol(cutoff)
    pool.extend(mc)
    per_outlet["Moneycontrol"] = len(mc)
    INGEST_STATS.clear()
    INGEST_STATS.update(per_outlet)
    logger.info("Outlet feeds: %d articles %s", len(pool), per_outlet)
    POOL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    POOL_CACHE.write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    return pool
