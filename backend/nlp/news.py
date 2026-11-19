"""
nlp/news.py
===========
Collects news headlines for an NSE company from Google News RSS (plus,
for the latest days, the direct outlet feeds in nlp/feeds.py) and keeps
only the ones that are really about that company.

Relevance rules (applied to the headline text):
  1. The headline must mention one of the company's aliases
     (e.g. "HDFC Bank"; short ALL-CAPS aliases such as "ITC" or "SBI"
     are matched case-sensitively so "itc" inside other words is ignored).
  2. It must not mention any of the company's exclusions
     (e.g. "SBI Life" is a different listed company from "SBI").
  3. Generic market wrap-ups ("Sensex, Nifty fall; top losers …") are
     dropped — they only restate price moves the stock signals already use.
  4. Near-duplicate headlines (syndicated copies, the same story from Google
     News and an outlet feed) are collapsed.

A past period can be searched with window=(start_date, end_date), which uses
Google News' after:/before: operators (used by Company Search and the
back-test). Downloads are cached in backend/cache/news/ so `--offline`
re-runs work.
"""

import logging
import re
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from config import CACHE_DIR, MARKET_WRAP_PATTERNS, NEWS_LOOKBACK_DAYS
from nlp.feeds import clean_text, normalize_outlet

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
    """Decode HTML entities, strip accents, unify quotes/dashes, collapse spaces."""
    text = unicodedata.normalize("NFKD", clean_text(text))
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
        self.aliases = [_term_regex(a) for a in aliases if a]
        self.exclude = [_term_regex(e) for e in exclude if e]

    def why_rejected(self, title: str) -> str | None:
        t = normalise(title)
        if not any(a.search(t) for a in self.aliases):
            return "not about company"
        if any(e.search(t) for e in self.exclude):
            return "excluded term"
        if _WRAP_RE.search(t):
            return "market wrap-up"
        return None


def dedupe_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:70]


# ── Fetching ─────────────────────────────────────────────────────────────────

def _time_operator(lookback_days: int, window: tuple[date, date] | None) -> str:
    if window:
        start, end = window
        return f" after:{start:%Y-%m-%d} before:{end + timedelta(days=1):%Y-%m-%d}"   # before: is exclusive
    return f" when:{lookback_days}d"


def _download_rss(query: str, retries: int = 3) -> bytes:
    url = GOOGLE_NEWS_RSS.format(q=urllib.parse.quote(query))
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
            "source": normalize_outlet(source) if source else "Google News",
            "url": it.findtext("link") or "",
            "provider": "google",
            "published": published.isoformat(),
            "date": published.astimezone(IST).date().isoformat(),   # NSE trading-day calendar
        })
    return items


def fetch_company_news(company: dict, offline: bool = False, lookback_days: int = NEWS_LOOKBACK_DAYS,
                       window: tuple[date, date] | None = None,
                       outlet_pool: list[dict] | None = None) -> tuple[list[dict], dict]:
    """
    Return (relevant_articles newest first, stats) for one company dict with
    symbol / name / query / aliases / exclude.
    stats = {"fetched": n, "kept": n, "rejected": {reason: n}, "providers": {name: n}}
    """
    sym = company.get("symbol") or re.sub(r"\W+", "_", company["name"])
    tag = f"_{window[0]:%Y%m%d}_{window[1]:%Y%m%d}" if window else ""
    cache = NEWS_CACHE / f"{sym.replace('&', '_and_')}{tag}.xml"
    raw = None
    if not offline:
        try:
            raw = _download_rss((company.get("query") or f'"{company["name"]}"') + _time_operator(lookback_days, window))
            cache.write_bytes(raw)
        except Exception as exc:
            logger.warning("%s: %s — falling back to cache", sym, exc)
    if raw is None and cache.exists():
        raw = cache.read_bytes()

    items = []
    if raw is not None:
        try:
            items = _parse_rss(raw)
        except ET.ParseError as exc:
            logger.warning("%s: could not parse Google News RSS (%s)", sym, exc)
    items += [dict(a) for a in (outlet_pool or [])]
    if window:
        lo, hi = window[0].isoformat(), window[1].isoformat()
        items = [a for a in items if lo <= a["date"] <= hi]

    filt = RelevanceFilter(company.get("aliases") or [company["name"]], company.get("exclude") or [])
    kept, rejected, seen, providers, fetched = [], {}, set(), {}, 0
    for a in sorted(items, key=lambda x: x["published"], reverse=True):
        reason = filt.why_rejected(a["title"])
        from_pool = a.get("provider", "google") != "google"
        if from_pool and reason == "not about company":
            continue                     # the outlet pool covers every company; only count its matches
        fetched += 1
        key = dedupe_key(a["title"])
        if reason is None and key in seen:
            reason = "duplicate"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        seen.add(key)
        kept.append(a)
        providers[a.get("provider", "google")] = providers.get(a.get("provider", "google"), 0) + 1
    return kept, {"fetched": fetched, "kept": len(kept), "rejected": rejected, "providers": providers}
