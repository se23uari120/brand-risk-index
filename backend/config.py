# =============================================================
# config.py — Central configuration for the Brand Risk pipeline
# =============================================================
#
# Everything that controls *how* the score is computed lives here,
# so the method can be audited (and tuned) in one place.

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent          # backend/
PROJECT_DIR  = BASE_DIR.parent                          # repo root
DATA_DIR     = BASE_DIR / "data"
OUTPUT_DIR   = BASE_DIR / "output"
CACHE_DIR    = BASE_DIR / "cache"                       # raw downloads (git-ignored)
MODELS_DIR   = BASE_DIR / "models"                      # FinBERT weights (git-ignored)

WATCHLIST_FILE   = DATA_DIR / "watchlist.json"
DIRECTORY_FILE   = DATA_DIR / "company_directory.json"
INCIDENTS_FILE   = DATA_DIR / "incidents.json"
LABELS_FILE      = DATA_DIR / "labels.json"
LATEST_FILE      = OUTPUT_DIR / "latest.json"
HISTORY_FILE     = OUTPUT_DIR / "history.json"
BACKTEST_FILE    = OUTPUT_DIR / "backtest.json"
FRONTEND_DATA_JS = PROJECT_DIR / "js" / "data.js"

for _d in (DATA_DIR, OUTPUT_DIR, CACHE_DIR, MODELS_DIR):
    _d.mkdir(exist_ok=True)

# ── Market data ───────────────────────────────────────────────
EXCHANGE_SUFFIX   = ".NS"        # Yahoo Finance suffix for NSE listings
BENCHMARK_SYMBOL  = "^NSEI"      # NIFTY 50 index
BENCHMARK_NAME    = "NIFTY 50"
PRICE_RANGE       = "1y"         # history downloaded per run
CHART_DAYS        = 126          # ~6 months of prices shipped to the dashboard

# Stock-signal windows (in trading days)
ESTIMATION_DAYS   = 120   # window used to learn each stock's betas & "normal" noise
EVENT_SHORT       = 5     # 1 week
EVENT_LONG        = 20    # ~1 month
VOL_SHORT         = 10    # recent volatility window
VOL_BASE          = 90    # baseline volatility window
VOLUME_SHORT      = 5     # recent volume window
VOLUME_BASE       = 60    # baseline volume window
DRAWDOWN_DAYS     = 63    # ~3 months look-back for lingering damage

# ── News ──────────────────────────────────────────────────────
NEWS_LOOKBACK_DAYS = 50   # how far back Google News is queried
NEWS_WINDOW_DAYS   = 7    # headlines from the last 7 days count toward the score
NEWS_KEEP_DAYS     = 14   # headlines shipped to the dashboard per company
NEWS_REQUEST_GAP_S = 1.0  # polite delay between Google News requests
# Time decay: a headline's weight halves every DECAY_HALF_LIFE_HOURS
# (report Sec. VIII/IX "add time decay").
DECAY_HALF_LIFE_HOURS = float(os.getenv("DECAY_HALF_LIFE_HOURS", "72"))
# Neutral pseudo-headlines added to the News-tone denominator so one or two
# headlines cannot produce an extreme value.
NEWS_PRIOR         = 2.0
# Bootstrap resamples of the headlines for the 90% score range
BOOTSTRAP_SAMPLES  = 200

# Generic market wrap-ups name many stocks at once and only restate the price
# move, which the stock signals already capture.
MARKET_WRAP_PATTERNS = [
    r"\bsensex\b", r"\bnifty\b", r"stocks? to (?:buy|watch)", r"top (?:gainers|losers)",
    r"stock market (?:today|live|update)", r"market (?:live|wrap)", r"share price live",
    r"buzzing stocks", r"stocks in news", r"hot stocks",
]

# Direct outlet feeds used next to Google News for the most recent days
# (checked live in Nov 2026; Moneycontrol's RSS is frozen, so its news
# sitemap is used instead — see nlp/feeds.py).
RSS_FEEDS = {
    "Business Standard": [
        "https://www.business-standard.com/rss/latest.rss",
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://www.business-standard.com/rss/companies-101.rss",
    ],
    "Economic Times": [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms",
    ],
    "Livemint": ["https://www.livemint.com/rss/companies", "https://www.livemint.com/rss/markets"],
    "Hindu BusinessLine": ["https://www.thehindubusinessline.com/companies/feeder/default.rss"],
    "CNBC-TV18": ["https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml"],
    "NDTV Profit": ["https://feeds.feedburner.com/ndtvprofit-latest"],
    "Times of India": ["https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"],
    "Indian Express": ["https://indianexpress.com/section/business/feed/"],
}
FEED_LOOKBACK_HOURS = 72

# ── Sentiment engine ─────────────────────────────────────────
FINBERT_MODEL = "ProsusAI/finbert"   # used when torch + transformers are installed
SENTIMENT_NEG_THRESHOLD = -0.15      # score at/below this → "negative" headline
SENTIMENT_POS_THRESHOLD = 0.15

# ── Risk levels (score 0–100) and prescribed actions ─────────
LEVEL_THRESHOLDS = {"moderate": 30, "high": 50}

LEVEL_GUIDANCE = {
    "Low":      "Normal behaviour. Background logging and routine monitoring; no escalation.",
    "Moderate": "Something unusual is happening. Assign an analyst, check disclosure (SEBI) obligations "
                "and draft a holding statement.",
    "High":     "Strong, company-specific stress. Start the executive crisis protocol: legal review, "
                "investor-relations alert and a real-time PR response.",
}

# ── History ───────────────────────────────────────────────────
BACKFILL_DAYS   = 30     # trading days scored on the first run
RECOMPUTE_DAYS  = 5      # most recent days re-scored on every run (late news, price fixes)
HISTORY_MAX     = 400    # trading days kept in history.json

# ── Back-test ─────────────────────────────────────────────────
BACKTEST_WINDOW_DAYS   = 5    # incident window: event day .. event day + 4
BACKTEST_CONTROL_DAYS  = 60   # control window: the same days, 60 days earlier
BACKTEST_MAX_PEERS     = 6    # sector peers fetched per incident

# ── Server (backend/api.py) ──────────────────────────────────
API_HOST = os.getenv("HOST", os.getenv("API_HOST", "127.0.0.1"))
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
REFRESH_MINUTES = float(os.getenv("REFRESH_MINUTES", "60"))       # live re-scoring interval
LIVE_REFRESH = os.getenv("LIVE_REFRESH", "true").lower() not in ("0", "false", "no")
