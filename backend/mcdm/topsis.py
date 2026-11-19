"""
mcdm/topsis.py
==============
TOPSIS — Technique for Order Preference by Similarity to Ideal Solution
(Hwang & Yoon, 1981).

Every criterion here is already a 0–100 "risk points" score where higher
means more brand risk (all cost-type), so the steps are:

1. Normalise         r_ij = x_ij / 100
2. Weight            v_ij = w_j · r_ij                     (w from AHP)
3. Ideal points      A+ = safest possible  = (0, …, 0)
                     A− = worst possible   = (w_1, …, w_n)   i.e. 100 on everything
4. Distances         D+_i = ‖v_i − A+‖      D−_i = ‖v_i − A−‖
5. Risk Index        RI_i = 100 · D+_i / (D+_i + D−_i)

Why fixed (absolute) ideal points?
  Classic TOPSIS takes A+ / A− from the best and worst company *in today's
  list*, so the riskiest company always scores 100 and the safest 0 — even on
  a calm day — and scores jump whenever the list changes. Anchoring A+ / A− to
  the theoretical extremes keeps the score comparable across days, which is
  what a tracker needs. (Set mode="relative" for the classic version.)

A useful property: TOPSIS uses Euclidean distance, so one severe signal is not
averaged away. With all criteria at 50 the index is 50, but a single maxed-out
criterion already lifts the index to ~50 even if the rest are 0.
"""

import numpy as np


class TOPSIS:
    def __init__(self, scores: np.ndarray, weights: np.ndarray, mode: str = "absolute"):
        self.X = np.atleast_2d(np.asarray(scores, float))   # (m companies, n criteria), 0–100
        self.w = np.asarray(weights, float)
        if self.X.shape[1] != len(self.w):
            raise ValueError("Number of criteria must match number of weights")
        self.mode = mode

    def run(self) -> dict:
        R = np.clip(self.X, 0, 100) / 100.0                      # step 1
        V = R * self.w                                           # step 2
        if self.mode == "absolute":                              # step 3
            a_pos, a_neg = np.zeros_like(self.w), self.w.copy()
        else:
            a_pos, a_neg = V.min(axis=0), V.max(axis=0)
        d_pos = np.sqrt(((V - a_pos) ** 2).sum(axis=1))          # step 4
        d_neg = np.sqrt(((V - a_neg) ** 2).sum(axis=1))
        denom = d_pos + d_neg
        cc = np.divide(d_pos, denom, out=np.zeros_like(d_pos), where=denom > 0)
        return {"V": V, "A_pos": a_pos, "A_neg": a_neg,
                "D_pos": d_pos, "D_neg": d_neg, "score": cc * 100}  # step 5


def topsis_score(criteria_row, weights) -> tuple[float, float, float]:
    """Convenience: (risk_index, D+, D−) for a single company."""
    out = TOPSIS(np.asarray(criteria_row, float)[None, :], weights).run()
    return float(out["score"][0]), float(out["D_pos"][0]), float(out["D_neg"][0])
