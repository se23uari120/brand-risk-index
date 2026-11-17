"""
nlp/text_ingestion.py
=====================
Real-time text ingestion from RSS feeds and Google News.

Fetches headlines + summaries for each monitored company and
returns raw text ready for FinBERT scoring.
Uses feedparser if available, otherwise falls back to Python's built-in
xml.etree.ElementTree with requests.
"""

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

import requests

from config import RSS_FEEDS

logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 24

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)
# Used when the India-scoped search returns nothing (e.g. non-Indian companies)
GOOGLE_NEWS_RSS_GLOBAL = (
    "https://news.google.com/rss/search"
    "?q={query}&hl=en-US&gl=US&ceid=US:en"
)


# Honest, self-identifying agent. Publishers such as Business Standard reject
# anonymous library defaults (python-requests / feedparser) but accept this.
FEED_HEADERS = {
    "User-Agent": "BrandRiskIndex/1.0 (RSS feed reader; academic research project)",
    "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

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


def normalize_outlet(name: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    for pattern, outlet in _OUTLET_ALIASES:
        if re.search(pattern, low):
            return outlet
    n = re.sub(r"^www\.", "", n, flags=re.I)
    return re.sub(r"\.(com|in|co\.in)$", "", n) or "Unknown"


def _clean_text(raw: str) -> str:
    """Strip HTML tags and excess whitespace from a string."""
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = html.unescape(html.unescape(clean))   # some feeds double-encode (&amp;amp;)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _parse_published(entry) -> Optional[datetime]:
    """Try to extract a timezone-aware datetime from a feed entry."""
    try:
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _fetch_rss_builtin(feed_url: str, lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """Fallback RSS parser using requests + xml.etree.ElementTree."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    articles = []
    headers = FEED_HEADERS
    try:
        resp = requests.get(feed_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return articles
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        source = channel.findtext("title") if channel is not None else feed_url

        items = root.findall(".//item")
        for item in items:
            title = _clean_text(item.findtext("title") or "")
            desc = _clean_text(item.findtext("description") or "")
            link = item.findtext("link") or ""
            pub_date = item.findtext("pubDate") or ""
            if title:
                articles.append({
                    "title": title,
                    "summary": desc,
                    "published": pub_date,
                    "source": source,
                    "url": link,
                })
    except Exception as exc:
        logger.debug("Builtin RSS parser encountered an issue for %s: %s", feed_url, exc)
    return articles


def fetch_rss_headlines(feed_url: str, lookback_hours: int = LOOKBACK_HOURS,
                        window: Optional[tuple] = None) -> List[dict]:
    """
    Fetch articles from a single RSS feed URL.
    window=(start, end) keeps articles published in that range instead of
    the last `lookback_hours`.
    """
    if not HAS_FEEDPARSER:
        return _fetch_rss_builtin(feed_url, lookback_hours)

    if window:
        cutoff, upper = window
    else:
        cutoff, upper = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours), None
    articles = []

    try:
        resp = requests.get(feed_url, headers=FEED_HEADERS, timeout=15)
        if resp.status_code != 200:
            logger.warning("Feed %s returned HTTP %s", feed_url, resp.status_code)
            return articles
        feed = feedparser.parse(resp.content)
        source = feed.feed.get("title", feed_url)

        for entry in feed.entries:
            published = _parse_published(entry)
            if published and (published < cutoff or (upper and published > upper)):
                continue

            title   = _clean_text(entry.get("title",   ""))
            summary = _clean_text(entry.get("summary", ""))

            if title:
                articles.append({
                    "title":     title,
                    "summary":   summary,
                    "published": published.isoformat() if published else None,
                    # Google News entries carry the real publisher in <source>
                    "source":    (entry.get("source") or {}).get("title") or source,
                    "outlet":    normalize_outlet((entry.get("source") or {}).get("title") or source),
                    "url":       entry.get("link", ""),
                })

    except Exception as exc:
        logger.warning("Failed to parse feed with feedparser: %s. Using builtin.", exc)
        return _fetch_rss_builtin(feed_url, lookback_hours)

    return articles


def _time_operator(lookback_hours: int, window: Optional[tuple]) -> str:
    """Google News search operators for the time window."""
    if window:
        start, end = window
        # before: is exclusive of that day, so add one day to include `end`
        return f"+after:{start:%Y-%m-%d}+before:{(end + timedelta(days=1)):%Y-%m-%d}"
    # "when:" returns the most recent items for the window (without it, the
    # feed is mostly older articles that the cutoff discards).
    return f"+when:{max(1, -(-lookback_hours // 24))}d"


def fetch_google_news(company_name: str, extra_terms: List[str] = None,
                      lookback_hours: int = LOOKBACK_HOURS,
                      window: Optional[tuple] = None) -> List[dict]:
    """
    Fetch articles from Google News RSS for a specific company.
    window=(start, end) searches a past date range (used for back-tests).
    """
    terms = [company_name]
    if extra_terms:
        terms += extra_terms

    # Search the name and its short aliases together ("Tata Motors" OR JLR) so
    # headlines that use the alias are found too; long keyword phrases are left
    # to the headline filter.
    names = [terms[0]] + [t for t in terms[1:] if t and len(t.split()) <= 3 and t.lower() != terms[0].lower()][:3]
    q = " OR ".join(f'"{t}"' if " " in t else t for t in names)
    query = requests.utils.quote(q) + _time_operator(lookback_hours, window)
    url = GOOGLE_NEWS_RSS.format(query=query)
    articles = fetch_rss_headlines(url, lookback_hours=lookback_hours, window=window)
    if not articles:
        url = GOOGLE_NEWS_RSS_GLOBAL.format(query=query)
        articles = fetch_rss_headlines(url, lookback_hours=lookback_hours, window=window)

    for a in articles:
        a["company_query"] = company_name

    return articles


# ── Moneycontrol ─────────────────────────────────────────────────────────────
# Moneycontrol's /rss/*.xml feeds stopped updating in 2024. Two live sources:
#   1. The official Google-News sitemap listed in moneycontrol.com/robots.txt
#      (~800 most recent articles, refreshed within minutes).
#   2. Google News restricted to site:moneycontrol.com for a specific company
#      (reaches further back than the sitemap for that company).
MONEYCONTROL_SITEMAP = "https://www.moneycontrol.com/news/news-sitemap.xml"
_SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
               "n": "http://www.google.com/schemas/sitemap-news/0.9"}
_mc_cache = {"ts": 0.0, "items": []}
MC_CACHE_SECONDS = 600


def _moneycontrol_section(url: str) -> str:
    m = re.search(r"moneycontrol\.com/(?:news/)?([a-z-]+)/", url)
    return m.group(1).replace("-", " ").title() if m else ""


def fetch_moneycontrol_sitemap(lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """Latest Moneycontrol articles from their official news sitemap (cached 10 min)."""
    if time.time() - _mc_cache["ts"] > MC_CACHE_SECONDS or not _mc_cache["items"]:
        items = []
        try:
            resp = requests.get(MONEYCONTROL_SITEMAP, headers=FEED_HEADERS, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for u in root.findall("s:url", _SITEMAP_NS):
                title = _clean_text(u.findtext("n:news/n:title", default="", namespaces=_SITEMAP_NS))
                if not title:
                    continue
                pub = u.findtext("n:news/n:publication_date", default="", namespaces=_SITEMAP_NS)
                try:
                    published = datetime.fromisoformat(pub).astimezone(timezone.utc)
                except ValueError:
                    published = None
                loc = u.findtext("s:loc", default="", namespaces=_SITEMAP_NS)
                section = _moneycontrol_section(loc)
                items.append({
                    "title":     title,
                    # keywords give the matcher (and FinBERT) a bit more context
                    "summary":   _clean_text(u.findtext("n:news/n:keywords", default="", namespaces=_SITEMAP_NS)),
                    "published": published.isoformat() if published else None,
                    "_published_dt": published,
                    "source":    "Moneycontrol" + (f" · {section}" if section else ""),
                    "provider":  "moneycontrol",
                    "outlet":    "Moneycontrol",
                    "url":       loc,
                })
            _mc_cache.update(ts=time.time(), items=items)
            logger.info("Moneycontrol sitemap: %d articles", len(items))
        except Exception as exc:
            logger.warning("Moneycontrol sitemap fetch failed: %s", exc)

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    return [{k: v for k, v in a.items() if k != "_published_dt"} for a in _mc_cache["items"]
            if a["_published_dt"] is None or a["_published_dt"] >= cutoff]


def fetch_moneycontrol_company(company_name: str, lookback_hours: int = LOOKBACK_HOURS,
                               window: Optional[tuple] = None) -> List[dict]:
    """Company-specific Moneycontrol articles via Google News (site:moneycontrol.com)."""
    query = requests.utils.quote(company_name) + "+site:moneycontrol.com" + _time_operator(lookback_hours, window)
    articles = fetch_rss_headlines(GOOGLE_NEWS_RSS.format(query=query), lookback_hours=lookback_hours,
                                   window=window)
    name_re = re.compile(r"(?<![\w])" + re.escape(company_name.lower()) + r"(?![\w])")
    out = []
    for a in articles:
        a["title"] = re.sub(r"\s+-\s+Moneycontrol(\.com)?$", "", a["title"], flags=re.I).strip()
        t = a["title"].lower()
        # Skip stock-listing / landing pages and stories that only mention the
        # company in the body (headline must name it, for scoring relevance).
        if (" | " in t or "nse, bse" in t or "stock/share" in t or "stock price" in t
                or len(t.split()) <= 4 or not name_re.search(t)):
            continue
        a["source"] = "Moneycontrol"
        a["outlet"] = "Moneycontrol"
        a["provider"] = "moneycontrol"
        out.append(a)
    return out


def ingest_all_feeds(lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """
    Fetch headlines from every configured outlet feed (in parallel) plus the
    Moneycontrol news sitemap. Each article is tagged with its outlet.
    """
    jobs = [(outlet, url) for outlet, urls in RSS_FEEDS.items() for url in urls]

    def _one(job):
        outlet, url = job
        batch = fetch_rss_headlines(url, lookback_hours=lookback_hours)
        for a in batch:
            a["outlet"] = outlet
            a["provider"] = "rss"
        return outlet, batch

    all_articles = []
    per_outlet = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for outlet, batch in pool.map(_one, jobs):
            all_articles.extend(batch)
            per_outlet[outlet] = per_outlet.get(outlet, 0) + len(batch)

    mc = fetch_moneycontrol_sitemap(lookback_hours)
    all_articles.extend(mc)
    per_outlet["Moneycontrol (sitemap)"] = len(mc)

    INGEST_STATS.clear()
    INGEST_STATS.update(per_outlet)
    logger.info("General feeds: %s", per_outlet)
    logger.info("Total general articles fetched: %d", len(all_articles))
    return all_articles


# Last per-outlet article counts from ingest_all_feeds (for /api/sources)
INGEST_STATS: Dict[str, int] = {}


def filter_by_company(articles: List[dict], search_terms: List[str],
                      headline_only: bool = True) -> List[dict]:
    """
    Filter articles by search terms. By default the HEADLINE must name the
    company: market wraps that only list it in the summary ("Sensex falls;
    Sun Pharma among losers") are not about its reputation.
    """
    # Word-boundary match so "ITC" doesn't match "switch"
    patterns = [re.compile(r"(?<![\w])" + re.escape(t.lower()) + r"(?![\w])")
                for t in search_terms if t and len(t) >= 2]
    matched = []
    for a in articles:
        haystack = a.get("title", "") if headline_only else a.get("title", "") + " " + a.get("summary", "")
        haystack = haystack.lower()
        if any(p.search(haystack) for p in patterns):
            matched.append(dict(a))
    return matched


def _brand_name(name: str) -> str:
    """'Paytm (One97)' -> 'Paytm', 'Infosys Ltd' -> 'Infosys'."""
    name = re.sub(r"\s*\(.*?\)", "", name).strip()
    return re.sub(r"\s+(ltd\.?|limited)$", "", name, flags=re.I).strip()


def _dedupe_key(title: str) -> str:
    # Google News appends " - Publisher"; strip it so the same story from the
    # Moneycontrol sitemap and Google News is only counted once.
    t = re.sub(r"\s+[-|]\s+[^-|]{2,40}$", "", title.lower())
    return re.sub(r"[^a-z0-9 ]", "", t)[:80]


def _strip_publisher(title: str) -> str:
    """Google News titles end in ' - Publisher'; drop it for display and scoring."""
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip()


def fetch_company_articles(company: dict,
                           general_pool: Optional[List[dict]] = None,
                           lookback_hours: int = LOOKBACK_HOURS,
                           window: Optional[tuple] = None) -> List[dict]:
    """
    Gather all relevant articles for a company.
    window=(start, end) fetches a past date range from Google News only
    (the outlet RSS feeds and the Moneycontrol sitemap only hold recent items).
    """
    search_terms = company.get("search_terms", [company["name"]])
    brand = _brand_name(company["name"])
    # Neutral name aliases (e.g. JLR, HUL, Eternal) are searched on Google News;
    # the registry's search_terms are only used to match headlines.
    aliases = [a for a in company.get("aliases", []) if a]
    terms = [brand] + aliases + [t for t in search_terms if t]
    # Headline must name the company (or one of its aliases) to count —
    # Google News also returns stories that only mention it in the body.
    name_res = [re.compile(r"(?<![\w])" + re.escape(t.lower()) + r"(?![\w])")
                for t in terms if len(t) >= 2]

    # Moneycontrol first so its copy wins de-duplication over Google's copy
    articles = fetch_moneycontrol_company(brand, lookback_hours=lookback_hours, window=window)

    if general_pool and not window:
        articles.extend(filter_by_company(general_pool, terms))

    dropped = 0
    for a in fetch_google_news(brand, extra_terms=aliases, lookback_hours=lookback_hours,
                               window=window):
        a.setdefault("provider", "google_news")
        a["title"] = _strip_publisher(a["title"])
        if not any(r.search(a["title"].lower()) for r in name_res):
            dropped += 1
            continue
        articles.append(a)
    if dropped:
        logger.info("Company %-25s → dropped %d Google News items that do not name it in the headline",
                    company["name"], dropped)

    seen = set()
    unique = []
    for a in articles:
        a.setdefault("provider", "rss")
        key = _dedupe_key(a["title"])
        if key not in seen:
            seen.add(key)
            unique.append(a)

    logger.info("Company %-25s → %d articles collected", company["name"], len(unique))
    return unique


def articles_to_texts(articles: List[dict]) -> List[str]:
    """
    Concatenate title + summary for each article into text string.
    """
    texts = []
    for a in articles:
        parts = [p for p in [a.get("title", ""), a.get("summary", "")] if p]
        texts.append(" ".join(parts))
    return texts
