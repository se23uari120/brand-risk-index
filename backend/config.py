# =============================================================
# config.py — Central configuration for the backend pipeline
# =============================================================

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
DATA_DIR    = BASE_DIR / "data"
OUTPUT_DIR  = BASE_DIR / "output"
MODELS_DIR  = BASE_DIR / "models"

DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# ── FinBERT model ─────────────────────────────────────────────
# ProsusAI/finbert is the standard HuggingFace FinBERT checkpoint.
# The pipeline auto-downloads it on first run (~500 MB).
FINBERT_MODEL = "ProsusAI/finbert"

# ── AHP weights (must sum to 1.0) ────────────────────────────
AHP_WEIGHTS = {
    "C1_severity":       0.35,
    "C2_reach":          0.28,
    "C3_recoverability": 0.22,
    "C4_criticality":    0.15,
}

# ── Risk level thresholds ─────────────────────────────────────
RISK_THRESHOLDS = {
    "Low":      (0,  40),
    "Moderate": (40, 70),
    "Critical": (70, 100),
}

# ── RSS / News feed sources ───────────────────────────────────
RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://feeds.feedburner.com/ndtvprofit-latest",
    "https://www.business-standard.com/rss/markets-106.rss",
]

# ── Reach velocity mapping ────────────────────────────────────
REACH_SCORE = {"Viral": 100, "High": 75, "Medium": 50, "Low": 25}

# ── Flask API settings ────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 5000))
DEBUG    = os.getenv("DEBUG", "false").lower() == "true"

