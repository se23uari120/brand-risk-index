"""
mcdm/sensitivity.py
===================
Sensitivity analysis of the AHP weights and the resulting ranking
(report Sec. VII-C: "sensitivity analysis of the AHP matrix (weights and
ranking stability)").

Three analyses on the current decision matrix:

1. Judgement perturbation — every upper-triangle judgement of the pairwise
   matrix is moved one step down and one step up the Saaty scale (12 variants).
   For each: new weights, CR, Spearman rank correlation with the base ranking,
   and how many companies change band.
2. One-at-a-time weight changes — each criterion weight is scaled by
   ±10/25/50% and the others rescaled proportionally.
3. Monte Carlo — 1,000 weight vectors drawn from a Dirichlet distribution
   centred on the AHP weights; per company, the 5–95% range of its index and
   how often it keeps its band and its rank.
"""

import numpy as np

from mcdm.ahp import AHP, DEFAULT_PAIRWISE, CRITERIA_NAMES
from mcdm.topsis import BASELINE_PROFILE, CRISIS_PROFILE, CRITERION_SCALE, _classify_level

SAATY = [1/9, 1/8, 1/7, 1/6, 1/5, 1/4, 1/3, 1/2, 1, 2, 3, 4, 5, 6, 7, 8, 9]
SHORT = ["C1", "C2", "C3", "C4"]


def _indices(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Vectorised anchored-TOPSIS index for every company (X: companies × 4, 0–100)."""
    V = X / CRITERION_SCALE * w
    a_pos = BASELINE_PROFILE / CRITERION_SCALE * w
    a_neg = CRISIS_PROFILE / CRITERION_SCALE * w
    dp = np.sqrt(((V - a_pos) ** 2).sum(axis=1))
    dn = np.sqrt(((V - a_neg) ** 2).sum(axis=1))
    return np.round(np.clip(dp / np.where(dp + dn == 0, 1e-9, dp + dn), 0, 1) * 100, 2)


def _ranks(x: np.ndarray) -> np.ndarray:
    """Rank 1 = highest index; ties get the average rank."""
    order = (-x).argsort(kind="stable")
    r = np.empty(len(x))
    r[order] = np.arange(1, len(x) + 1)
    for v in np.unique(x):  # average ties
        m = x == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = _ranks(np.asarray(a, float)), _ranks(np.asarray(b, float))
    if ra.std() == 0 or rb.std() == 0:
        return 1.0
    return float(np.corrcoef(ra, rb)[0, 1])


def _bands(x):
    return np.array([_classify_level(v) for v in x])


def _summary(base_idx, idx):
    return {
        "spearman": round(spearman(base_idx, idx), 4),
        "band_changes": int((_bands(base_idx) != _bands(idx)).sum()),
        "max_index_change": round(float(np.abs(idx - base_idx).max()), 2),
        "top_changed": bool(np.argmax(idx) != np.argmax(base_idx)),
    }


def _step(value: float, direction: int):
    i = min(range(len(SAATY)), key=lambda k: abs(SAATY[k] - value))
    j = i + direction
    return SAATY[j] if 0 <= j < len(SAATY) else None


def judgement_perturbation(X, base_idx):
    out = []
    n = DEFAULT_PAIRWISE.shape[0]
    for i in range(n):
        for j in range(i + 1, n):
            for d in (-1, +1):
                new = _step(DEFAULT_PAIRWISE[i, j], d)
                if new is None:
                    continue
                A = DEFAULT_PAIRWISE.copy()
                A[i, j], A[j, i] = new, 1 / new
                res = AHP(A).compute()
                w = np.array(list(res["weights"].values()))
                idx = _indices(X, w)
                out.append({
                    "judgement": f"{SHORT[i]} vs {SHORT[j]}",
                    "from": _fmt(DEFAULT_PAIRWISE[i, j]), "to": _fmt(new),
                    "weights": [round(float(x), 4) for x in w],
                    "CR": float(res["CR"]), "consistent": bool(res["CR_acceptable"]),
                    **_summary(base_idx, idx),
                })
    return out


def _fmt(v):
    return str(int(round(v))) if v >= 1 else f"1/{int(round(1 / v))}"


def one_at_a_time(X, w0, base_idx, deltas=(-0.5, -0.25, -0.1, 0.1, 0.25, 0.5)):
    out = []
    for k in range(len(w0)):
        for d in deltas:
            w = w0.copy()
            w[k] = w0[k] * (1 + d)
            others = [i for i in range(len(w0)) if i != k]
            w[others] = w0[others] * (1 - w[k]) / w0[others].sum()
            idx = _indices(X, w)
            out.append({"criterion": SHORT[k], "change_pct": int(d * 100),
                        "weights": [round(float(x), 4) for x in w], **_summary(base_idx, idx)})
    return out


def monte_carlo(X, w0, base_idx, names, draws=1000, concentration=60.0, seed=11):
    rng = np.random.default_rng(seed)
    W = rng.dirichlet(w0 * concentration, size=draws)
    all_idx = np.array([_indices(X, w) for w in W])            # draws × companies
    base_rank = _ranks(base_idx)
    base_band = _bands(base_idx)
    rho = np.array([spearman(base_idx, row) for row in all_idx])
    comp = []
    for c, name in enumerate(names):
        col = all_idx[:, c]
        ranks = np.array([_ranks(row)[c] for row in all_idx])
        comp.append({
            "name": name,
            "base_index": float(base_idx[c]),
            "p5": round(float(np.percentile(col, 5)), 1),
            "p95": round(float(np.percentile(col, 95)), 1),
            "band_stability": round(float((_bands(col) == base_band[c]).mean()), 3),
            "rank_stability": round(float((ranks == base_rank[c]).mean()), 3),
        })
    w_lo, w_hi = np.percentile(W, 5, axis=0), np.percentile(W, 95, axis=0)
    return {
        "draws": draws, "concentration": concentration,
        "weight_range": [{"criterion": SHORT[k], "p5": round(float(w_lo[k]), 3), "p95": round(float(w_hi[k]), 3)}
                         for k in range(len(w0))],
        "spearman_mean": round(float(rho.mean()), 4),
        "spearman_p5": round(float(np.percentile(rho, 5)), 4),
        "companies": sorted(comp, key=lambda c: -c["base_index"]),
    }


def run_sensitivity(records: list[dict], weights) -> dict:
    """records: dicts with name and C1..C4 (e.g. latest.json)."""
    names = [r["name"] for r in records]
    X = np.array([[float(r.get(c, 0)) for c in CRITERIA_NAMES] for r in records])
    w0 = np.asarray(weights, float)
    base_idx = _indices(X, w0)
    return {
        "criteria": CRITERIA_NAMES,
        "base_weights": [round(float(x), 4) for x in w0],
        "companies": len(names),
        "judgements": judgement_perturbation(X, base_idx),
        "one_at_a_time": one_at_a_time(X, w0, base_idx),
        "monte_carlo": monte_carlo(X, w0, base_idx, names),
    }
