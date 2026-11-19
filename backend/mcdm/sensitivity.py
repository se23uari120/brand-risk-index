"""
mcdm/sensitivity.py
===================
How much do the results depend on the AHP weights? (report Sec. VII-C:
"sensitivity analysis of the AHP matrix (weights and ranking stability)"
and Sec. IX-4: "combine expert weights with objective weights").

Run on today's decision matrix (companies × 5 criteria):

1. CRITIC objective weights (mcdm/critic.py) compared with the AHP weights,
   plus a 50/50 blend and equal weights — with the ranking each produces.
2. Judgement perturbation — every upper-triangle judgement of the pairwise
   matrix moved one step down and one step up the Saaty scale. For each:
   new weights, consistency ratio, Spearman rank correlation with today's
   ranking and how many companies change level.
3. One-at-a-time — each weight scaled by ±10/25/50% (others rescaled).
4. Monte Carlo — 1,000 weight vectors drawn around the AHP weights
   (Dirichlet); per company, the 5–95% range of its score and how often it
   keeps its level and its rank.

Scores use the same fixed-ideal TOPSIS as the live index.
"""

import numpy as np

from config import LEVEL_THRESHOLDS
from mcdm.ahp import AHP, CRITERIA_KEYS, DEFAULT_PAIRWISE
from mcdm.critic import combine_weights, critic_weights

SAATY = [1/9, 1/8, 1/7, 1/6, 1/5, 1/4, 1/3, 1/2, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def indices(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Fixed-ideal TOPSIS score for every company (X: companies × criteria, 0–100)."""
    V = np.clip(X, 0, 100) / 100 * w
    dp = np.sqrt((V ** 2).sum(axis=1))
    dn = np.sqrt(((w - V) ** 2).sum(axis=1))
    return np.where(dp + dn > 0, dp / np.where(dp + dn == 0, 1, dp + dn), 0) * 100


def ranks(x: np.ndarray) -> np.ndarray:
    """Rank 1 = highest score; ties share the average rank."""
    x = np.asarray(x, float)
    order = (-x).argsort(kind="stable")
    r = np.empty(len(x))
    r[order] = np.arange(1, len(x) + 1)
    for v in np.unique(x):
        m = x == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def spearman(a, b) -> float:
    ra, rb = ranks(a), ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return 1.0
    return float(np.corrcoef(ra, rb)[0, 1])


def bands(x) -> np.ndarray:
    hi, mo = LEVEL_THRESHOLDS["high"], LEVEL_THRESHOLDS["moderate"]
    return np.where(np.asarray(x) >= hi, 2, np.where(np.asarray(x) >= mo, 1, 0))


def _summary(base, idx):
    return {"spearman": round(spearman(base, idx), 4),
            "bandChanges": int((bands(base) != bands(idx)).sum()),
            "maxChange": round(float(np.abs(idx - base).max()), 2),
            "topChanged": bool(np.argmax(idx) != np.argmax(base))}


def _fmt(v):
    return str(int(round(v))) if v >= 1 else f"1/{int(round(1 / v))}"


def _step(value, direction):
    i = min(range(len(SAATY)), key=lambda k: abs(SAATY[k] - value))
    j = i + direction
    return SAATY[j] if 0 <= j < len(SAATY) else None


def judgement_perturbation(X, base):
    out, n = [], DEFAULT_PAIRWISE.shape[0]
    for i in range(n):
        for j in range(i + 1, n):
            for d in (-1, +1):
                new = _step(DEFAULT_PAIRWISE[i, j], d)
                if new is None:
                    continue
                A = DEFAULT_PAIRWISE.copy()
                A[i, j], A[j, i] = new, 1 / new
                res = AHP(A).compute()
                w = np.array(res["weights"])
                out.append({"judgement": f"{CRITERIA_KEYS[i]} vs {CRITERIA_KEYS[j]}",
                            "from": _fmt(DEFAULT_PAIRWISE[i, j]), "to": _fmt(new),
                            "weights": [round(float(x), 4) for x in w], "CR": round(res["CR"], 4),
                            "consistent": res["consistent"], **_summary(base, indices(X, w))})
    return out


def one_at_a_time(X, w0, base, deltas=(-0.5, -0.25, -0.1, 0.1, 0.25, 0.5)):
    out = []
    for k in range(len(w0)):
        for d in deltas:
            w = w0.copy()
            w[k] = w0[k] * (1 + d)
            others = [i for i in range(len(w0)) if i != k]
            w[others] = w0[others] * (1 - w[k]) / w0[others].sum()
            out.append({"criterion": CRITERIA_KEYS[k], "changePct": int(round(d * 100)),
                        "weights": [round(float(x), 4) for x in w], **_summary(base, indices(X, w))})
    return out


def monte_carlo(X, w0, base, symbols, draws=1000, concentration=60.0, seed=11):
    rng = np.random.default_rng(seed)
    W = rng.dirichlet(w0 * concentration, size=draws)
    all_idx = np.array([indices(X, w) for w in W])          # draws × companies
    base_rank, base_band = ranks(base), bands(base)
    rank_mat = np.array([ranks(row) for row in all_idx])
    rho = np.array([spearman(base, row) for row in all_idx])
    comp = [{"symbol": s, "score": round(float(base[c]), 1),
             "p5": round(float(np.percentile(all_idx[:, c], 5)), 1),
             "p95": round(float(np.percentile(all_idx[:, c], 95)), 1),
             "levelStability": round(float((bands(all_idx[:, c]) == base_band[c]).mean()), 3),
             "rankStability": round(float((rank_mat[:, c] == base_rank[c]).mean()), 3)}
            for c, s in enumerate(symbols)]
    return {"draws": draws, "concentration": concentration,
            "weightRange": [{"criterion": CRITERIA_KEYS[k], "p5": round(float(np.percentile(W[:, k], 5)), 3),
                             "p95": round(float(np.percentile(W[:, k], 95)), 3)} for k in range(len(w0))],
            "spearmanMean": round(float(rho.mean()), 4), "spearmanP5": round(float(np.percentile(rho, 5)), 4),
            "companies": sorted(comp, key=lambda c: -c["score"])}


def run_mcdm_analysis(records: list[dict], ahp_weights) -> dict:
    """records: dicts with 'symbol' and 'criteria' (5 numbers, 0–100)."""
    symbols = [r["symbol"] for r in records]
    X = np.array([r["criteria"] for r in records], dtype=float)
    w0 = np.asarray(ahp_weights, float)
    base = indices(X, w0)

    crit = critic_weights(X)
    wc = crit["weights"]
    variants = {"AHP": w0, "CRITIC": wc, "Blend 50/50": combine_weights(w0, wc, 0.5),
                "Equal": np.full(len(w0), 1 / len(w0))}
    comparison = []
    for name, w in variants.items():
        idx = indices(X, w)
        comparison.append({"name": name, "weights": [round(float(x), 4) for x in w],
                           "levels": {lab: int((bands(idx) == k).sum()) for k, lab in enumerate(["Low", "Moderate", "High"])},
                           "top": [symbols[i] for i in np.argsort(-idx)[:5]], **_summary(base, idx)})
    return {
        "criteria": CRITERIA_KEYS,
        "companies": len(symbols),
        "critic": {"weights": [round(float(x), 4) for x in wc], "sigma": [round(float(x), 4) for x in crit["sigma"]],
                   "correlation": [[round(float(v), 3) for v in row] for row in crit["correlation"]]},
        "comparison": comparison,
        "judgements": judgement_perturbation(X, base),
        "oneAtATime": one_at_a_time(X, w0, base),
        "monteCarlo": monte_carlo(X, w0, base, symbols),
    }
