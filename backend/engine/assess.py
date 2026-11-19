"""
engine/assess.py
================
Scores ONE company from its prices and headlines. Shared by the daily
pipeline (engine/risk_scorer.py), Company Search (api.py) and the
back-test (engine/backtest.py), so every score is on the same scale.

For each trading day in the requested window (point-in-time):
  prices up to day t      → stock signals → C1 C2 C3
  headlines in (t−7d, t]  → recency-weighted sentiment → C4 C5
  AHP weights + TOPSIS    → risk score 0–100

For the latest day it also returns the issue type behind the negative
coverage (crisis classifier), the regulators mentioned, a 90% range for the
score from bootstrapping the headlines, and the shares of the weighted total.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone

import numpy as np

from config import (BOOTSTRAP_SAMPLES, CHART_DAYS, LEVEL_THRESHOLDS, NEWS_KEEP_DAYS,
                    NEWS_WINDOW_DAYS)
from engine.criteria import news_arrays, news_from_arrays, stock_criteria
from market.stock_signals import compute_stock_signals
from mcdm.topsis import topsis_score
from nlp.crisis_classifier import GENERAL, classify, regulators_mentioned

IST = timezone(timedelta(hours=5, minutes=30))
NO_ISSUE = "No significant adverse coverage"


def level_for(score: float) -> str:
    if score >= LEVEL_THRESHOLDS["high"]:
        return "High"
    if score >= LEVEL_THRESHOLDS["moderate"]:
        return "Moderate"
    return "Low"


def _r(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if np.isnan(x) else round(x, nd)


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, dtime(23, 59, 59), tzinfo=IST).astimezone(timezone.utc)


def score_headlines(articles: list[dict], sentiment) -> None:
    """Add sentiment, label, category and regulators to each article in place."""
    todo = [a for a in articles if "sentiment" not in a]
    if todo:
        for a, s in zip(todo, sentiment.score_batch([a["title"] for a in todo])):
            a["sentiment"], a["label"] = s["score"], s["label"]
    for a in articles:
        if "category" not in a:
            a["category"] = classify(a["title"])["category"]
            a["regulators"] = regulators_mentioned(a["title"])


def issues(window: list[dict], w: np.ndarray) -> dict:
    """Which kind of issue drives the negative coverage (weighted by recency × negativity)."""
    stats = defaultdict(lambda: {"articles": 0, "negative": 0, "weight": 0.0})
    for a, wi in zip(window, w):
        st = stats[a["category"]]
        st["articles"] += 1
        if a["label"] == "negative":
            st["negative"] += 1
            st["weight"] += float(wi) * max(0.0, -float(a["sentiment"]))
    total = sum(v["weight"] for v in stats.values()) or 1.0
    cats = sorted(({"category": k, "articles": v["articles"], "negative": v["negative"],
                    "share": round(v["weight"] / total, 3)} for k, v in stats.items()),
                  key=lambda c: (-c["share"], -c["negative"], -c["articles"]))
    real = [c for c in cats if c["negative"] and c["category"] != GENERAL]
    any_neg = any(c["negative"] for c in cats)
    dominant = real[0]["category"] if real else (GENERAL if any_neg else NO_ISSUE)
    regs = Counter(r for a in window if a["label"] == "negative" for r in a.get("regulators", []))
    return {"dominant": dominant, "categories": [c for c in cats if c["negative"]][:5],
            "regulators": dict(regs.most_common(5))}


def bootstrap_range(window: list[dict], stock_crit, weights, as_of, samples=BOOTSTRAP_SAMPLES, seed=7):
    """5–95% range of the score when the headline set is resampled with replacement."""
    if len(window) < 3 or not samples:
        return None
    sent, neg, opinion, w = news_arrays(window, as_of)
    rng = np.random.default_rng(seed)
    n, out = len(window), []
    for _ in range(samples):
        k = rng.integers(0, n, n)
        c4, c5 = news_from_arrays(sent[k], neg[k], opinion[k], w[k])
        out.append(topsis_score([*stock_crit, c4, c5], weights)[0])
    return [round(float(np.percentile(out, 5)), 1), round(float(np.percentile(out, 95)), 1)]


def assess_company(co: dict, prices, info: dict, peer, bench, articles: list[dict], weights,
                   today: date, now: datetime, n_days: int, bootstrap: bool = True) -> dict:
    """
    co: watchlist-style dict (symbol, name, sector). prices/bench: DataFrames up to the
    as-of day. articles: already scored with score_headlines(). today: the as-of calendar
    day (news up to it counts for the latest row); now: UTC time used for recency weights
    on that latest row.
    """
    signals, path = compute_stock_signals(prices, bench, peer, n_days, CHART_DAYS)
    if signals.empty:
        raise RuntimeError("not enough price history (needs about 7 months)")
    art_dates = [date.fromisoformat(a["date"]) for a in articles]

    daily = {}
    last_day = signals.index[-1].date()
    for ts, sig in signals.iterrows():
        d = ts.date()
        latest = d == last_day
        end = max(d, today) if latest else d
        as_of = now if (latest and end == today) else end_of_day(end)
        start = end - timedelta(days=NEWS_WINDOW_DAYS)
        window = [a for a, ad in zip(articles, art_dates) if start < ad <= end]
        stock = stock_criteria(sig)
        sent, neg, opinion, w = news_arrays(window, as_of) if window else ([], [], [], np.array([]))
        c4, c5 = news_from_arrays(sent, neg, opinion, w) if window else (0.0, 0.0)
        crit = [*stock, c4, c5]
        score, d_pos, d_neg = topsis_score(crit, weights)
        daily[d.isoformat()] = {"score": score, "criteria": crit, "dPos": d_pos, "dNeg": d_neg,
                                "window": window, "w": w, "sig": sig, "as_of": as_of, "stock": stock}

    cur = daily[last_day.isoformat()]
    sig, window = cur["sig"], cur["window"]
    weighted = [wj * c for wj, c in zip(weights, cur["criteria"])]
    total = sum(weighted) or 1.0
    recent_cut = today - timedelta(days=NEWS_KEEP_DAYS)
    issue = issues(window, cur["w"]) if window else {"dominant": NO_ISSUE, "categories": [], "regulators": {}}
    rng = bootstrap_range(window, cur["stock"], weights, cur["as_of"]) if bootstrap else None

    return {
        "symbol": co["symbol"],
        "name": co["name"],
        "legalName": info.get("longName"),
        "sector": co["sector"],
        "asOf": last_day.isoformat(),
        "score": _r(cur["score"], 1),
        "level": level_for(cur["score"]),
        "range": rng,
        "criteria": [_r(c, 1) for c in cur["criteria"]],
        "shares": [_r(x / total, 3) for x in weighted],
        "topsis": {"dPos": _r(cur["dPos"], 4), "dNeg": _r(cur["dNeg"], 4)},
        "issue": issue,
        "stock": {
            "close": _r(sig["close"], 2),
            "beta": _r(sig["beta"], 2), "betaSector": _r(sig["beta_sector"], 2),
            "hasPeers": peer is not None,
            "ret5": _r(sig["ret5"], 4), "ret20": _r(sig["ret20"], 4),
            "idxRet5": _r(sig["idx_ret5"], 4), "idxRet20": _r(sig["idx_ret20"], 4),
            "peerRet5": _r(sig["peer_ret5"], 4),
            "excess5": _r(sig["excess5"], 4), "excess20": _r(sig["excess20"], 4),
            "z5": _r(sig["z5"], 2), "z20": _r(sig["z20"], 2), "sigma": _r(sig["sigma"], 4),
            "volRatio": _r(sig["vol_ratio"], 2), "volumeRatio": _r(sig["volume_ratio"], 2),
            "abnDrawdown": _r(sig["abn_drawdown"], 4), "ddSigma": _r(sig["dd_sigma"], 2),
            "high52": info.get("fiftyTwoWeekHigh"), "low52": info.get("fiftyTwoWeekLow"),
        },
        "news": {
            "count7d": len(window),
            "neg7d": sum(a["label"] == "negative" for a in window),
            "pos7d": sum(a["label"] == "positive" for a in window),
            "outlets7d": len({a["source"] for a in window}),
            "articles": [
                {"t": a["title"], "s": a["source"], "u": a["url"], "d": a["date"],
                 "sc": _r(a["sentiment"], 2), "l": a["label"], "c": a["category"]}
                for a in articles if date.fromisoformat(a["date"]) > recent_cut and date.fromisoformat(a["date"]) <= today
            ][:15],
        },
        "_daily": {d: v["score"] for d, v in daily.items()},
        "_window": window,
        "_closes": prices["close"],
        "_path": path,
    }
