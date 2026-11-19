"""
engine/live_scoring.py
======================
Turns a set of FinBERT-scored articles about ONE company into the four
criterion scores of report Table III, the AHP-TOPSIS risk index, a
confidence interval and an explanation.

Used for both the monitored companies and Company Search, so every
company is on the same scale.

Definitions (report Table III, with the "negative effective sentiment" s
made explicit):

  w_i   = 0.5 ** (age_i / half_life)              time-decay weight
  neg_i = max(0, -score_i)                        FinBERT negative intensity
  s     = Σ w_i·neg_i / (Σ w_i + PRIOR)           over opinionated (non-neutral)
                                                  articles; PRIOR neutral
                                                  pseudo-articles damp tiny samples
  C1 Severity        = clip[5,100](s × 100)                              (1)
  C2 Reach           = Viral 100 / High 75 / Medium 50 / Low 25, from the
                       time-weighted volume of negative articles and the
                       number of outlets carrying them
  C3 Recoverability  = clip[10,100](0.6·C1 + 0.4·C2)                     (2)
  C4 Criticality     = clip[10,100](m_k · C1)                            (3)
  Risk Index         = D+ / (D+ + D−) × 100 against fixed baseline (A+)
                       and crisis (A−) profiles                          (5)
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np

from config import (REACH_SCORE, SECTOR_SENSITIVITY, DEFAULT_SECTOR_SENSITIVITY,
                    DECAY_HALF_LIFE_HOURS, SEVERITY_PRIOR, BOOTSTRAP_SAMPLES)
from mcdm.topsis import anchored_index, CRITERIA
from nlp.crisis_classifier import tag_articles, GENERAL

REACH_RULES = [  # (label, min weighted negative volume, min outlets with negative coverage)
    ("Viral", 15.0, 8),
    ("High", 6.0, 4),
    ("Medium", 2.0, 2),
]


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def decay_weights(articles: List[dict], as_of: Optional[datetime] = None,
                  half_life: float = DECAY_HALF_LIFE_HOURS) -> np.ndarray:
    as_of = as_of or datetime.now(tz=timezone.utc)
    ages = []
    for a in articles:
        dt = _parse_dt(a.get("published"))
        ages.append(None if dt is None else max(0.0, (as_of - dt).total_seconds() / 3600))
    known = [x for x in ages if x is not None]
    fill = float(np.median(known)) if known else 0.0  # undated articles: typical age
    return np.array([0.5 ** ((fill if x is None else x) / half_life) for x in ages])


def sector_multiplier(sector: str) -> float:
    return SECTOR_SENSITIVITY.get(sector or "", DEFAULT_SECTOR_SENSITIVITY)


def _arrays(articles):
    score = np.array([float(a.get("sentiment", 0.0)) for a in articles])
    label = np.array([a.get("label", "neutral") for a in articles])
    outlet = np.array([a.get("outlet") or a.get("source") or "Unknown" for a in articles])
    return score, label, outlet


def _severity(score, label, w):
    opinion = label != "neutral"
    neg = np.where(opinion, np.maximum(0.0, -score), 0.0)
    num = float((w * neg).sum())
    den = float((w * opinion).sum()) + SEVERITY_PRIOR
    return num / den, w * neg


def _reach(label, outlet, w):
    is_neg = label == "negative"
    volume = float(w[is_neg].sum())
    outlets = len(set(outlet[is_neg].tolist()))
    for name, vol_min, out_min in REACH_RULES:
        if volume >= vol_min or outlets >= out_min:
            return name, volume, outlets
    return "Low", volume, outlets


def _criteria(s, reach_label, mk):
    c1 = float(np.clip(s * 100, 5, 100))
    c2 = float(REACH_SCORE.get(reach_label, 25))
    c3 = float(np.clip(0.6 * c1 + 0.4 * c2, 10, 100))
    c4 = float(np.clip(mk * c1, 10, 100))
    return {"C1_severity": round(c1, 2), "C2_reach": round(c2, 2),
            "C3_recoverability": round(c3, 2), "C4_criticality": round(c4, 2)}


def criteria_from_arrays(score, label, outlet, w, mk):
    s, _ = _severity(score, label, w)
    reach_label, _, _ = _reach(label, outlet, w)
    return _criteria(s, reach_label, mk)


def score_company_articles(articles: List[dict], sector: str, weights,
                           as_of: Optional[datetime] = None,
                           bootstrap: int = BOOTSTRAP_SAMPLES,
                           seed: int = 7) -> dict:
    """
    Full live assessment for one company. `articles` must already carry
    FinBERT 'sentiment' (signed score) and 'label'. Adds 'weight',
    'category', 'regulators' and 'severity_share' to each article in place.
    """
    as_of = as_of or datetime.now(tz=timezone.utc)
    weights = np.asarray(weights, dtype=float)
    mk = sector_multiplier(sector)
    if not articles:
        crit = _criteria(0.0, "Low", mk)
        return {**crit, **anchored_index(crit, weights), "article_count": 0}

    if "category" not in articles[0]:
        tag_articles(articles)
    score, label, outlet = _arrays(articles)
    w = decay_weights(articles, as_of)

    s, contrib = _severity(score, label, w)
    reach_label, neg_volume, neg_outlets = _reach(label, outlet, w)
    crit = _criteria(s, reach_label, mk)
    res = anchored_index(crit, weights)

    total_contrib = float(contrib.sum()) or 1.0
    for a, wi, ci in zip(articles, w, contrib):
        a["weight"] = round(float(wi), 3)
        a["severity_share"] = round(float(ci) / total_contrib, 4) if contrib.sum() else 0.0

    # ── Confidence interval: bootstrap the article set ───────────────────
    ci_low = ci_high = res["risk_index"]
    if bootstrap and len(articles) >= 3:
        rng = np.random.default_rng(seed)
        n = len(articles)
        idx_samples = []
        for _ in range(bootstrap):
            pick = rng.integers(0, n, n)
            c = criteria_from_arrays(score[pick], label[pick], outlet[pick], w[pick], mk)
            idx_samples.append(anchored_index(c, weights)["risk_index"])
        ci_low, ci_high = (float(np.percentile(idx_samples, q)) for q in (5, 95))

    # ── Crisis categories (dominant issue) ───────────────────────────────
    cat_stats = defaultdict(lambda: {"articles": 0, "negative": 0, "neg_weight": 0.0})
    for a, ci in zip(articles, contrib):
        st = cat_stats[a["category"]]
        st["articles"] += 1
        st["negative"] += int(a.get("label") == "negative")
        st["neg_weight"] += float(ci)
    neg_total = sum(v["neg_weight"] for v in cat_stats.values()) or 1.0
    categories = sorted(
        ({"category": k, "articles": v["articles"], "negative": v["negative"],
          "share_of_severity": round(v["neg_weight"] / neg_total, 4)}
         for k, v in cat_stats.items()),
        key=lambda c: (-c["share_of_severity"], -c["articles"]))

    negatives = [a for a in articles if a.get("label") == "negative"]
    issue_cats = [c for c in categories if c["negative"] > 0 and c["category"] != GENERAL]
    if issue_cats:
        dominant_category = issue_cats[0]["category"]
    elif negatives:
        dominant_category = GENERAL
    else:
        dominant_category = "No significant adverse coverage"
    in_cat = [a for a in negatives if a["category"] == dominant_category] or negatives
    worst = min(in_cat, key=lambda a: a.get("sentiment", 0)) if in_cat else None

    # ── Drivers: the articles contributing most to severity ──────────────
    drivers = sorted((a for a in articles if a.get("severity_share", 0) > 0),
                     key=lambda a: -a["severity_share"])[:6]

    # ── Daily timeline ───────────────────────────────────────────────────
    days = defaultdict(lambda: {"articles": 0, "negative": 0, "positive": 0, "sum": 0.0})
    for a in articles:
        dt = _parse_dt(a.get("published"))
        if not dt:
            continue
        d = days[dt.date().isoformat()]
        d["articles"] += 1
        d["negative"] += int(a.get("label") == "negative")
        d["positive"] += int(a.get("label") == "positive")
        d["sum"] += float(a.get("sentiment", 0.0))
    timeline = [{"date": k, "articles": v["articles"], "negative": v["negative"],
                 "positive": v["positive"], "avg_sentiment": round(v["sum"] / v["articles"], 3)}
                for k, v in sorted(days.items())]

    regulators = Counter(r for a in negatives for r in a.get("regulators", []))
    labels = Counter(label.tolist())

    return {
        **crit,
        **res,
        "ci_low": round(ci_low, 1),
        "ci_high": round(ci_high, 1),
        "ci_levels": sorted({_level(ci_low), res["level"], _level(ci_high)},
                            key=["Low", "Moderate", "Critical"].index),
        "negative_effective_sentiment": round(s, 4),
        "compound_sentiment": round(float(score.mean()), 4),
        "negative_ratio": round(labels.get("negative", 0) / len(articles), 4),
        "label_counts": {k: labels.get(k, 0) for k in ("negative", "neutral", "positive")},
        "article_count": len(articles),
        "reach_label": reach_label,
        "negative_volume": round(neg_volume, 2),
        "negative_outlets": neg_outlets,
        "sector_multiplier": mk,
        "dominant_category": dominant_category,
        "dominant_crisis": (worst or {}).get("title", "No significant adverse coverage")[:140],
        "categories": categories,
        "regulators": dict(regulators.most_common()),
        "drivers": [{k: a.get(k) for k in ("title", "outlet", "url", "published", "sentiment",
                                           "category", "weight", "severity_share")}
                    for a in drivers],
        "timeline": timeline,
        "as_of": as_of.isoformat(),
        "explanation": _explain(crit, res, s, reach_label, neg_volume, neg_outlets,
                                labels, len(articles), dominant_category, mk, sector),
    }


def _level(x):
    return "Low" if x < 40 else "Moderate" if x < 70 else "Critical"


def _explain(crit, res, s, reach_label, volume, outlets, labels, n, cat, mk, sector):
    shares = res["contributions"]
    top = max(shares, key=shares.get)
    names = {"C1_severity": "severity", "C2_reach": "reach",
             "C3_recoverability": "recoverability", "C4_criticality": "criticality"}
    out = [
        f"{labels.get('negative', 0)} of {n} articles are negative, {labels.get('positive', 0)} positive. "
        f"Weighted by recency, opinionated coverage has a negative intensity of {s:.2f}, "
        f"giving severity C1 = {crit['C1_severity']:.0f}.",
        f"Reach is {reach_label} ({volume:.1f} recency-weighted negative articles across {outlets} "
        f"outlet{'s' if outlets != 1 else ''}), "
        f"so C2 = {crit['C2_reach']:.0f}.",
        f"Sector multiplier {mk:.2f}{' (' + sector + ')' if sector else ''} gives criticality C4 = {crit['C4_criticality']:.0f}.",
        f"The index is {res['risk_index']:.1f}; {names[top]} accounts for {shares[top] * 100:.0f}% of the "
        f"distance from the lowest-risk baseline.",
    ]
    if cat not in ("No significant adverse coverage",):
        out.append(f"Dominant issue type: {cat}.")
    return out


__all__ = ["score_company_articles", "decay_weights", "criteria_from_arrays", "CRITERIA"]
