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

# ── AHP weights ──────────────────────────────────────────────
# The weights in use are COMPUTED from the pairwise matrix in mcdm/ahp.py
# (report Table IV). The old 0.35 / 0.28 / 0.22 / 0.15 figures did not match
# the matrix and have been replaced by the computed values (λmax = 4.031,
# CI = 0.0103, CR = 0.0115). tests/test_mcdm.py checks they stay in sync.
AHP_WEIGHTS = {
    "C1_severity":       0.4658,
    "C2_reach":          0.2771,
    "C3_recoverability": 0.1611,
    "C4_criticality":    0.0960,
}

# ── Live scoring parameters ──────────────────────────────────
# Time decay: an article's weight halves every DECAY_HALF_LIFE_HOURS
# (report Sec. VIII/IX: "add time decay").
DECAY_HALF_LIFE_HOURS = float(os.getenv("DECAY_HALF_LIFE_HOURS", "72"))
# Severity shrinkage: SEVERITY_PRIOR neutral pseudo-articles are added to the
# denominator so one or two headlines cannot produce an extreme severity.
SEVERITY_PRIOR = 2.0
# Bootstrap resamples for the risk-index confidence interval
BOOTSTRAP_SAMPLES = 200

# ── Sector sensitivity multipliers (C4 Criticality) ─────────
# Report Table III: 0.65 for FMCG up to 1.15 for FinTech.
SECTOR_SENSITIVITY = {
    "Banking & Finance": 1.10,
    "FinTech":           1.15,
    "NBFC":              1.05,
    "Insurance":         1.00,
    "Consumer Tech":     0.95,
    "Aviation":          0.95,
    "EdTech":            0.95,
    "Healthcare":        0.90,
    "Automotive":        0.85,
    "Infrastructure":    0.85,
    "Energy & Power":    0.85,
    "Real Estate":       0.85,
    "Telecom":           0.80,
    "Metals & Mining":   0.80,
    "Media":             0.80,
    "IT Services":       0.75,
    "Retail":            0.75,
    "Conglomerate":      0.70,
    "Engineering":       0.70,
    "Cement & Materials": 0.70,
    "FMCG":              0.65,
}
DEFAULT_SECTOR_SENSITIVITY = 0.80

# ── Risk level thresholds ─────────────────────────────────────
RISK_THRESHOLDS = {
    "Low":      (0,  40),
    "Moderate": (40, 70),
    "Critical": (70, 100),
}

# ── RSS / News feed sources (grouped by outlet) ───────────────
# Fetched with a self-identifying feed-reader User-Agent: Business Standard
# returns 403 to anonymous library agents. Checked live on 14 Nov 2026.
# Moneycontrol's /rss/*.xml feeds are frozen since 2024, so Moneycontrol is
# ingested from its news sitemap + Google News (see nlp/text_ingestion.py).
# Not usable: Zee Business (403), Financial Express (empty feed).
RSS_FEEDS = {
    "Business Standard": [
        "https://www.business-standard.com/rss/latest.rss",
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://www.business-standard.com/rss/companies-101.rss",
        "https://www.business-standard.com/rss/economy-102.rss",
    ],
    "Economic Times": [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
        "https://economictimes.indiatimes.com/news/company/rssfeeds/2143429.cms",
        "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms",
    ],
    "Livemint": [
        "https://www.livemint.com/rss/companies",
        "https://www.livemint.com/rss/markets",
        "https://www.livemint.com/rss/news",
    ],
    "Hindu BusinessLine": [
        "https://www.thehindubusinessline.com/companies/feeder/default.rss",
        "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    ],
    "The Hindu": ["https://www.thehindu.com/business/feeder/default.rss"],
    "CNBC-TV18": ["https://www.cnbctv18.com/commonfeeds/v1/cne/rss/latest.xml"],
    "NDTV Profit": ["https://feeds.feedburner.com/ndtvprofit-latest"],
    "Times of India": ["https://timesofindia.indiatimes.com/rssfeeds/1898055.cms"],
    "Indian Express": ["https://indianexpress.com/section/business/feed/"],
}

# ── Reach velocity mapping ────────────────────────────────────
REACH_SCORE = {"Viral": 100, "High": 75, "Medium": 50, "Low": 25}

# ── Flask API settings ────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 5000))
DEBUG    = os.getenv("DEBUG", "false").lower() == "true"

