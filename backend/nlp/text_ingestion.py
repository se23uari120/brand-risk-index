"""
nlp/text_ingestion.py
=====================
Real-time text ingestion from RSS feeds and Google News.

Fetches headlines + summaries for each monitored company and
returns raw text ready for FinBERT scoring.
Uses feedparser if available, otherwise falls back to Python's built-in
xml.etree.ElementTree with requests.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
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
    "?q={query}+India&hl=en-IN&gl=IN&ceid=IN:en"
)


def _clean_text(raw: str) -> str:
    """Strip HTML tags and excess whitespace from a string."""
    clean = re.sub(r"<[^>]+>", " ", raw)
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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


def fetch_rss_headlines(feed_url: str, lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """
    Fetch articles from a single RSS feed URL.
    """
    if not HAS_FEEDPARSER:
        return _fetch_rss_builtin(feed_url, lookback_hours)

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=lookback_hours)
    articles = []

    try:
        feed = feedparser.parse(feed_url)
        source = feed.feed.get("title", feed_url)

        for entry in feed.entries:
            published = _parse_published(entry)
            if published and published < cutoff:
                continue

            title   = _clean_text(entry.get("title",   ""))
            summary = _clean_text(entry.get("summary", ""))

            if title:
                articles.append({
                    "title":     title,
                    "summary":   summary,
                    "published": published.isoformat() if published else None,
                    "source":    source,
                    "url":       entry.get("link", ""),
                })

    except Exception as exc:
        logger.warning("Failed to parse feed with feedparser: %s. Using builtin.", exc)
        return _fetch_rss_builtin(feed_url, lookback_hours)

    return articles


def fetch_google_news(company_name: str, extra_terms: List[str] = None,
                      lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """
    Fetch articles from Google News RSS for a specific company.
    """
    terms = [company_name]
    if extra_terms:
        terms += extra_terms

    query = requests.utils.quote(terms[0])
    url = GOOGLE_NEWS_RSS.format(query=query)
    articles = fetch_rss_headlines(url, lookback_hours=lookback_hours)

    for a in articles:
        a["company_query"] = company_name

    return articles


def ingest_all_feeds(lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """
    Fetch headlines from all configured general RSS feeds.
    """
    all_articles = []
    for url in RSS_FEEDS:
        logger.info("Fetching general RSS: %s", url)
        batch = fetch_rss_headlines(url, lookback_hours=lookback_hours)
        all_articles.extend(batch)
        time.sleep(0.2)

    logger.info("Total general articles fetched: %d", len(all_articles))
    return all_articles


def filter_by_company(articles: List[dict], search_terms: List[str]) -> List[dict]:
    """
    Filter articles by search terms.
    """
    terms_lower = [t.lower() for t in search_terms]
    matched = []
    for a in articles:
        haystack = (a.get("title", "") + " " + a.get("summary", "")).lower()
        if any(term in haystack for term in terms_lower):
            matched.append(a)
    return matched


def fetch_company_articles(company: dict,
                           general_pool: Optional[List[dict]] = None,
                           lookback_hours: int = LOOKBACK_HOURS) -> List[dict]:
    """
    Gather all relevant articles for a company.
    """
    search_terms = company.get("search_terms", [company["name"]])

    articles = fetch_google_news(
        company["name"],
        extra_terms=search_terms[1:],
        lookback_hours=lookback_hours,
    )

    if general_pool:
        matched = filter_by_company(general_pool, search_terms)
        articles.extend(matched)

    seen = set()
    unique = []
    for a in articles:
        key = a["title"].lower()[:80]
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
