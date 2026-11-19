"""
engine/criteria.py
==================
The five risk criteria. Each converts raw evidence into 0–100 "risk points"
(0 = nothing unusual, 100 = as alarming as this signal gets).

Stock effect (always available for a listed company)
  C1 Market reaction    — did the stock fall more than the market and sector explain?
  C2 Trading stress     — is it being traded unusually nervously while falling?
  C3 Lingering damage   — has company-specific damage built up and stayed?
News (only when there are headlines)
  C4 News tone          — how negative is the recent opinionated coverage?
  C5 Negative coverage  — how much negative coverage (recency-weighted)?

News headlines are weighted by recency: w = 0.5^(age / 72 h), so a story
from today counts fully and one from a week ago about a fifth.

The text in CRITERIA is shipped to the dashboard so the explanations shown to
users always match the code that produced the numbers.
"""

import math
from datetime import datetime, timezone

import numpy as np

from config import DECAY_HALF_LIFE_HOURS, NEWS_PRIOR

HALF_LIFE = DECAY_HALF_LIFE_HOURS

CRITERIA = [
    {
        "key": "C1", "name": "Market reaction", "group": "Stock",
        "question": "Did the share price fall more than the market and its sector can explain?",
        "how": ("From the previous 6 months we learn how each stock normally moves with the NIFTY 50 and "
                "with its sector peers. We subtract the move they explain; what is left is the "
                "company-specific (abnormal) return. We add it up over the last week and the last month "
                "and divide by the stock's usual day-to-day noise to get a z-score — so a 5% drop counts "
                "for more in a calm stock than in a jumpy one, and a sector-wide sell-off does not count."),
        "formula": "C1 = 100 × clip( (max(−z₅, −z₂₀) − 1) ÷ 2 , 0 , 1 )",
        "scale": "0 down to −1σ (everyday noise) · 50 at −2σ (~2% chance) · 100 at −3σ or worse",
    },
    {
        "key": "C2", "name": "Trading stress", "group": "Stock",
        "question": "Is the stock being traded unusually nervously?",
        "how": ("Compares the last 10 days' volatility with the previous 90 days, and the last 5 days' "
                "volume with the previous 60 days. Spikes mean investors are reacting to something. "
                "If the stock is actually beating the market this week, the spike is likely good news, "
                "so it only counts for a quarter."),
        "formula": "C2 = ½·clip((vol ratio − 1) ÷ 1.5) + ½·clip((volume ratio − 1) ÷ 2), ×0.25 if beating the market",
        "scale": "0 at normal activity · 100 when volatility is 2.5× and volume 3× normal while falling",
    },
    {
        "key": "C3", "name": "Lingering damage", "group": "Stock",
        "question": "Has company-specific damage built up and stayed?",
        "how": ("Adds up the company-specific (abnormal) returns day by day into a performance line, then "
                "measures how far that line now sits below its best point of the last 3 months. This is "
                "damage that has not recovered yet. Some gap is always normal, so it is measured in units "
                "of the stock's usual 3-month wobble (σ × √63)."),
        "formula": "C3 = 100 × clip( (gap in σ-units − 1) ÷ 2 , 0 , 1 )",
        "scale": "0 up to 1σ (normal) · 50 at 2σ behind (~5% chance) · 100 at 3σ or more behind",
    },
    {
        "key": "C4", "name": "News tone", "group": "News",
        "question": "How negative is the recent opinionated coverage?",
        "how": ("Every relevant headline from the last 7 days gets a sentiment score from −1 to +1 and a "
                f"recency weight (halving every {HALF_LIFE:.0f} hours). Over the opinionated headlines "
                "(negative or positive — routine neutral news does not water a crisis down) we take the "
                f"weighted average negativity, adding {NEWS_PRIOR:.0f} imaginary neutral headlines so one stray "
                "story cannot spike the score. With no headlines this is 0 and the score rests on the stock."),
        "formula": f"C4 = 100 × Σ wᵢ·max(0, −sᵢ) ÷ (Σ wᵢ + {NEWS_PRIOR:.0f})   over non-neutral headlines",
        "scale": "0 with no news or only positive news · ~40 for a few clearly negative stories · →100 for many",
    },
    {
        "key": "C5", "name": "Negative coverage", "group": "News",
        "question": "How much negative coverage did the company get in the last 7 days?",
        "how": ("Adds up the recency weights of the headlines labelled negative — a measure of how loudly "
                "and how recently the bad news was carried. The first few stories matter most and it "
                "levels off, because ten stories about the same issue are not ten times worse than one."),
        "formula": "C5 = 100 × (1 − e^(−Σ wᵢ over negative headlines ÷ 5))",
        "scale": "1 fresh story → 18 · 3 → 45 · 5 → 63 · 10 → 86",
    },
]


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def stock_criteria(sig: dict) -> tuple[float, float, float]:
    """C1, C2, C3 from one day of stock signals (see market/stock_signals.py)."""
    # the first 1σ of underperformance is everyday noise
    c1 = 100 * _clip01((max(-sig["z5"], -sig["z20"]) - 1) / 2)

    s_vol = _clip01((sig["vol_ratio"] - 1) / 1.5)
    s_volume = _clip01((sig["volume_ratio"] - 1) / 2)
    c2 = 100 * (s_vol + s_volume) / 2
    if sig["car5"] >= 0:            # stress while out-performing = likely positive attention
        c2 *= 0.25

    c3 = 100 * _clip01((sig["dd_sigma"] - 1) / 2)
    return c1, c2, c3


def recency_weights(articles: list[dict], as_of: datetime) -> np.ndarray:
    """w = 0.5^(age_hours / half-life) for each article (as_of is a UTC datetime)."""
    out = []
    for a in articles:
        pub = datetime.fromisoformat(a["published"])
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (as_of - pub).total_seconds() / 3600)
        out.append(0.5 ** (age_h / HALF_LIFE))
    return np.array(out, dtype=float)


def news_from_arrays(sent: np.ndarray, neg: np.ndarray, opinion: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """C4, C5 from arrays (also used by the bootstrap)."""
    if not len(sent):
        return 0.0, 0.0
    neg_int = np.maximum(0.0, -sent) * opinion
    c4 = 100 * float((w * neg_int).sum()) / (float((w * opinion).sum()) + NEWS_PRIOR)
    c5 = 100 * (1 - math.exp(-float(w[neg].sum()) / 5))
    return c4, c5


def news_arrays(articles: list[dict], as_of: datetime):
    sent = np.array([float(a["sentiment"]) for a in articles], dtype=float)
    labels = [a["label"] for a in articles]
    neg = np.array([lab == "negative" for lab in labels], dtype=bool)
    opinion = np.array([lab != "neutral" for lab in labels], dtype=float)
    return sent, neg, opinion, recency_weights(articles, as_of)


def news_criteria(articles: list[dict], as_of: datetime) -> tuple[float, float]:
    """C4, C5 from the headlines inside the 7-day window (each needs sentiment, label, published)."""
    return news_from_arrays(*news_arrays(articles, as_of))
