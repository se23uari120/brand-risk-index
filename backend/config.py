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
LATEST_FILE      = OUTPUT_DIR / "latest.json"
HISTORY_FILE     = OUTPUT_DIR / "history.json"
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
ESTIMATION_DAYS   = 120   # window used to learn each stock's beta & "normal" noise
EVENT_SHORT       = 5     # 1 week
EVENT_LONG        = 20    # ~1 month
VOL_SHORT         = 10    # recent volatility window
VOL_BASE          = 90    # baseline volatility window
VOLUME_SHORT      = 5     # recent volume window
VOLUME_BASE       = 60    # baseline volume window
DRAWDOWN_DAYS     = 63    # ~3 months look-back for the relative peak

# ── News ──────────────────────────────────────────────────────
NEWS_LOOKBACK_DAYS = 50   # how far back Google News is queried
NEWS_WINDOW_DAYS   = 7    # headlines from the last 7 days count toward the score
NEWS_PRIOR         = 2    # "phantom" neutral headlines (stops one story spiking C4)
NEWS_KEEP_DAYS     = 14   # headlines shipped to the dashboard per company
NEWS_REQUEST_GAP_S = 1.0  # polite delay between Google News requests

# Headlines that are generic market wrap-ups (they name many stocks at once and
# just repeat the price move, which the stock signals already capture).
MARKET_WRAP_PATTERNS = [
    r"\bsensex\b", r"\bnifty\b", r"stocks? to (?:buy|watch)", r"top (?:gainers|losers)",
    r"stock market (?:today|live|update)", r"market (?:live|wrap)", r"share price live",
    r"buzzing stocks", r"stocks in news", r"hot stocks",
]

# ── Sentiment engine ─────────────────────────────────────────
FINBERT_MODEL = "ProsusAI/finbert"   # used when torch + transformers are installed
SENTIMENT_NEG_THRESHOLD = -0.15      # score at/below this → "negative" headline
SENTIMENT_POS_THRESHOLD = 0.15

# ── Risk levels (score 0–100) ────────────────────────────────
LEVEL_THRESHOLDS = {"moderate": 30, "high": 50}

LEVEL_GUIDANCE = {
    "Low":      "Normal behaviour. Keep routine monitoring.",
    "Moderate": "Something unusual is happening. Review the headlines and price action; prepare a holding statement.",
    "High":     "Strong, company-specific stress. Escalate to communications / IR and respond quickly.",
}

# ── History ───────────────────────────────────────────────────
BACKFILL_DAYS   = 30     # trading days scored on the first run
RECOMPUTE_DAYS  = 5      # most recent days re-scored on every run (late news, price fixes)
HISTORY_MAX     = 400    # trading days kept in history.json

# ── Optional REST API ────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))
