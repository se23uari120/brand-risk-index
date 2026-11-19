"""
nlp/news.py
===========
Collects recent news headlines for each NSE company from Google News RSS
and keeps only the ones that are really about that company.

Relevance rules (applied to the headline text):
  1. The headline must mention one of the company's aliases
     (e.g. "HDFC Bank"; short ALL-CAPS aliases such as "ITC" or "SBI"
     are matched case-sensitively so "itc" inside other words is ignored).
  2. It must not mention any of the company's exclusions
     (e.g. "SBI Life" is a different listed company from "SBI").
  3. Generic market wrap-ups ("Sensex, Nifty fall; top losers …") are
     dropped — they only restate price moves the stock signals already use.
  4. Near-duplicate headlines (syndicated copies) are collapsed.

Downloads are cached in backend/cache/news/ so `--offline` re-runs work.
"""

import json
import logging
import re
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from config import CACHE_DIR, MARKET_WRAP_PATTERNS, NEWS_LOOKBACK_DAYS

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
NEWS_CACHE = CACHE_DIR / "news"
NEWS_CACHE.mkdir(parents=True, exist_ok=True)
IST = timezone(timedelta(hours=5, minutes=30))

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) brand-risk-monitor"
_WRAP_RE = re.compile("|".join(MARKET_WRAP_PATTERNS), re.IGNORECASE)


# ── Text helpers ─────────────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Strip accents, unify quotes/dashes and collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def _term_regex(term: str) -> re.Pattern:
    """Match a whole term (works for terms containing & . ' too)."""
    case_sensitive = term.isupper() and len(term) <= 5
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(normalise(term)) + r"(?![A-Za-z0-9])", flags)


class RelevanceFilter:
    def __init__(self, aliases: list[str], exclude: list[str]):
        self.aliases = [_term_regex(a) for a in aliases]
        self.exclude = [_term_regex(e) for e in exclude]

    def why_rejected(self, title: str) -> str | None:
        t = normalise(title)
        if not any(a.search(t) for a in self.aliases):
            return "not about company"
        if any(e.search(t) for e in self.exclude):
            return "excluded term"
        if _WRAP_RE.search(t):
            return "market wrap-up"
        return None


# ── Fetching ─────────────────────────────────────────────────────────────────

def _download_rss(query: str, lookback_days: int, retries: int = 3) -> bytes:
    url = GOOGLE_NEWS_RSS.format(q=urllib.parse.quote(f"{query} when:{lookback_days}d"))
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = _session.get(url, timeout=20)
            r.raise_for_status()
            return r.content
        except Exception as exc:
            last = exc
            time.sleep(2 * attempt)
    raise RuntimeError(f"Google News request failed: {last}")


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        title = normalise(it.findtext("title") or "")
        source = normalise(it.findtext("source") or "")
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        try:
            published = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            continue
        if not title:
            continue
        items.append({
            "title": title,
            "source": source or "Google News",
            "url": it.findtext("link") or "",
            "published": published.isoformat(),
            "date": published.astimezone(IST).date().isoformat(),   # NSE trading-day calendar
        })
    return items


def fetch_company_news(company: dict, offline: bool = False,
                       lookback_days: int = NEWS_LOOKBACK_DAYS) -> tuple[list[dict], dict]:
    """
    Return (relevant_articles, stats) for one watchlist entry.
    stats = {"fetched": n, "kept": n, "rejected": {reason: n}}
    """
    cache = NEWS_CACHE / f"{company['symbol'].replace('&', '_and_')}.xml"
    raw = None
    if not offline:
        try:
            raw = _download_rss(company["query"], lookback_days)
            cache.write_bytes(raw)
        except Exception as exc:
            logger.warning("%s: %s — falling back to cache", company["symbol"], exc)
    if raw is None:
        if not cache.exists():
            return [], {"fetched": 0, "kept": 0, "rejected": {}, "error": "no news data"}
        raw = cache.read_bytes()

    try:
        items = _parse_rss(raw)
    except ET.ParseError as exc:
        logger.warning("%s: could not parse RSS (%s)", company["symbol"], exc)
        return [], {"fetched": 0, "kept": 0, "rejected": {}, "error": "parse error"}

    filt = RelevanceFilter(company.get("aliases") or [company["name"]], company.get("exclude") or [])
    kept, rejected, seen = [], {}, set()
    for a in sorted(items, key=lambda x: x["published"], reverse=True):
        reason = filt.why_rejected(a["title"])
        key = re.sub(r"[^a-z0-9]", "", a["title"].lower())[:70]
        if reason is None and key in seen:
            reason = "duplicate"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        seen.add(key)
        kept.append(a)
    return kept, {"fetched": len(items), "kept": len(kept), "rejected": rejected}
