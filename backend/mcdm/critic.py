"""
mcdm/critic.py
==============
CRITIC objective weighting (Diakoulaki, Mavrotas & Papayannakis, 1995).

Report Sec. IX-4 recommends combining the expert AHP weights with objective
weights. CRITIC gives more weight to criteria that (a) vary more across the
companies and (b) are less correlated with the other criteria:

    C_j = σ_j · Σ_k (1 − r_jk)        w_j = C_j / Σ C_j

All four criteria are cost-type (higher = riskier), so the min–max
normalisation is applied in the same direction for each.
"""

import numpy as np


def critic_weights(X: np.ndarray) -> dict:
    """X: (companies × criteria). Returns weights, std devs and correlations."""
    X = np.asarray(X, dtype=float)
    m, n = X.shape
    lo, hi = X.min(axis=0), X.max(axis=0)
    rng = np.where(hi - lo == 0, 1.0, hi - lo)
    Z = (X - lo) / rng
    sigma = Z.std(axis=0, ddof=1) if m > 1 else np.zeros(n)

    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.corrcoef(Z, rowvar=False)
    R = np.nan_to_num(np.atleast_2d(R), nan=0.0)
    np.fill_diagonal(R, 1.0)

    info = sigma * (1.0 - R).sum(axis=0)
    total = info.sum()
    w = info / total if total > 0 else np.full(n, 1.0 / n)
    return {"weights": w, "sigma": sigma, "correlation": R, "information": info}


def combine_weights(w_subjective, w_objective, alpha: float = 0.5) -> np.ndarray:
    """Linear combination α·AHP + (1−α)·CRITIC, renormalised."""
    w = alpha * np.asarray(w_subjective, float) + (1 - alpha) * np.asarray(w_objective, float)
    return w / w.sum()
