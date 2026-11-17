"""
mcdm/topsis.py
==============
TOPSIS (Technique for Order Preference by Similarity to Ideal Solution).

Takes a decision matrix of company criterion scores and returns
a Risk Index (0–100) for each company using the TOPSIS closeness
coefficient scaled by AHP weights.

All four criteria are COST-type (higher score = higher risk).

Reference:
  Hwang, C. L., & Yoon, K. (1981). Multiple Attribute Decision Making.
  Lecture Notes in Economics and Mathematical Systems, Springer.
"""

import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CRITERIA = ["C1_severity", "C2_reach", "C3_recoverability", "C4_criticality"]

# Fixed reference profiles (report Sec. IV-D: "A+ is the lowest-risk baseline
# and A- is maximum crisis exposure"). The baseline is the lowest profile the
# Table III formulas can produce: C1 floor 5, Low reach 25, C3 = 0.6*5+0.4*25 = 13,
# C4 floor 10. The crisis profile is 100 on every criterion.
BASELINE_PROFILE = np.array([5.0, 25.0, 13.0, 10.0])
CRISIS_PROFILE   = np.array([100.0, 100.0, 100.0, 100.0])
CRITERION_SCALE  = 100.0


class TOPSIS:
    """
    TOPSIS scorer.

    Parameters
    ----------
    decision_matrix : DataFrame, shape (n_companies, n_criteria)
                      Each value must be in [0, 100] (normalised criterion score).
    weights         : array-like of length n_criteria (AHP priority weights).
    criteria_names  : column names (default: CRITERIA list above).
    mode            : "anchored" (default) — criteria are already on a common
                      0–100 scale, so they are divided by 100 and A+/A- are the
                      fixed BASELINE/CRISIS profiles. A company's index then does
                      not depend on which other companies are scored with it,
                      so a searched company and the monitored set share one scale.
                      "relative" — classic TOPSIS: vector normalisation and
                      A+/A- taken from the column min/max of this matrix
                      (scores are relative to the set; kept for comparison).
    """

    def __init__(self,
                 decision_matrix: pd.DataFrame,
                 weights: np.ndarray,
                 criteria_names: list[str] = None,
                 mode: str = "anchored"):
        if mode not in ("anchored", "relative"):
            raise ValueError("mode must be 'anchored' or 'relative'")
        self.mode   = mode
        self.X      = decision_matrix.values.astype(float)   # (m, n)
        self.w      = np.asarray(weights, dtype=float)        # (n,)
        self.cols   = criteria_names or CRITERIA
        self.labels = list(decision_matrix.index)

        assert self.X.shape[1] == len(self.w), \
            "Number of criteria must match number of weights."

        # Computed in run()
        self.R:   np.ndarray = None   # normalised matrix
        self.V:   np.ndarray = None   # weighted normalised matrix
        self.A_pos: np.ndarray = None  # ideal best  (A+)
        self.A_neg: np.ndarray = None  # ideal worst (A-)
        self.D_pos: np.ndarray = None  # distance to A+
        self.D_neg: np.ndarray = None  # distance to A-
        self.CC:    np.ndarray = None  # closeness coefficient
        self.scores: np.ndarray = None # final risk index (0–100)

    # ── Step-by-step TOPSIS ──────────────────────────────────────────────────

    def _step1_normalize(self):
        """
        Step 1: Normalisation.
        anchored: r_ij = x_ij / 100          (common 0–100 criterion scale)
        relative: r_ij = x_ij / sqrt(sum(x_ij^2))   (vector normalisation)
        """
        if self.mode == "anchored":
            self.R = self.X / CRITERION_SCALE
            return
        denom  = np.sqrt((self.X ** 2).sum(axis=0))
        denom[denom == 0] = 1e-9          # guard against zero columns
        self.R = self.X / denom

    def _step2_weight(self):
        """
        Step 2: Weighted normalised matrix.
        v_ij = w_j * r_ij
        """
        self.V = self.R * self.w

    def _step3_ideal_solutions(self):
        """
        Step 3: Ideal best A+ and ideal worst A-.
        Because all criteria are COST-type (higher = worse):
          A+ = column minimums (ideal best = lowest risk exposure)
          A- = column maximums (ideal worst = highest risk exposure)
        In anchored mode they are the fixed baseline / crisis profiles.
        """
        if self.mode == "anchored":
            self.A_pos = BASELINE_PROFILE / CRITERION_SCALE * self.w
            self.A_neg = CRISIS_PROFILE / CRITERION_SCALE * self.w
            return
        self.A_pos = self.V.min(axis=0)   # best  solution per criterion
        self.A_neg = self.V.max(axis=0)   # worst solution per criterion

    def _step4_distances(self):
        """
        Step 4: Euclidean distances.
        D+_i = sqrt(sum((v_ij - A+_j)^2))
        D-_i = sqrt(sum((v_ij - A-_j)^2))
        """
        self.D_pos = np.sqrt(((self.V - self.A_pos) ** 2).sum(axis=1))
        self.D_neg = np.sqrt(((self.V - self.A_neg) ** 2).sum(axis=1))

    def _step5_closeness(self):
        """
        Step 5: Closeness coefficient for Risk Index.
        D+_i: Euclidean distance from lowest-risk baseline (A+).
        D-_i: Euclidean distance from highest-risk crisis state (A-).
        
        Risk Index Closeness:
        CC_i = D+_i / (D+_i + D-_i)
        Ranges [0, 1]: 1.0 = closest to maximum crisis risk, 0.0 = closest to safe baseline.
        """
        denom       = self.D_pos + self.D_neg
        denom[denom == 0] = 1e-9
        self.CC     = np.clip(self.D_pos / denom, 0.0, 1.0)
        # Scale to [0, 100]
        self.scores = np.round(self.CC * 100, 2)

    # ── Public API ───────────────────────────────────────────────────────────

    def run(self) -> pd.DataFrame:
        """
        Execute all TOPSIS steps and return a results DataFrame.

        Returns
        -------
        DataFrame with columns:
          company, risk_index, cc, d_pos, d_neg, level, action
        Sorted by risk_index descending.
        """
        logger.info("Running TOPSIS for %d companies, %d criteria …",
                    len(self.labels), len(self.cols))

        self._step1_normalize()
        self._step2_weight()
        self._step3_ideal_solutions()
        self._step4_distances()
        self._step5_closeness()

        results = pd.DataFrame({
            "company":    self.labels,
            "risk_index": self.scores,
            "cc":         np.round(self.CC, 4),
            "d_pos":      np.round(self.D_pos, 4),
            "d_neg":      np.round(self.D_neg, 4),
        })

        # Add risk level classification
        results["level"]  = results["risk_index"].apply(_classify_level)
        results["action"] = results["level"].apply(_action_trigger)

        results = results.sort_values("risk_index", ascending=False).reset_index(drop=True)
        results.index += 1   # 1-based rank

        logger.info("TOPSIS complete. Top risk: %s (%.1f)",
                    results.iloc[0]["company"], results.iloc[0]["risk_index"])
        return results

    def weighted_matrix_df(self) -> pd.DataFrame:
        """Return the weighted normalised matrix as a labelled DataFrame."""
        if self.V is None:
            raise RuntimeError("Call run() first.")
        return pd.DataFrame(self.V, index=self.labels, columns=self.cols)

    def contributions(self) -> pd.DataFrame:
        """
        Share of each criterion in the squared distance from the baseline (D+^2).
        Explains which criteria push a company away from the lowest-risk profile.
        """
        if self.V is None:
            raise RuntimeError("Call run() first.")
        sq = (self.V - self.A_pos) ** 2
        tot = sq.sum(axis=1, keepdims=True)
        tot[tot == 0] = 1e-12
        return pd.DataFrame(sq / tot, index=self.labels, columns=self.cols)

    def ideal_solutions_df(self) -> pd.DataFrame:
        """Return A+ and A- as a labelled DataFrame."""
        if self.A_pos is None:
            raise RuntimeError("Call run() first.")
        return pd.DataFrame(
            {"A+ (best)": self.A_pos, "A- (worst)": self.A_neg},
            index=self.cols,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def classify_level(score: float) -> str:
    return _classify_level(score)


def action_for_level(level: str) -> str:
    return _action_trigger(level)


def _classify_level(score: float) -> str:
    """Map a risk index (0–100) to Low / Moderate / Critical (report Table V)."""
    if score < 40:
        return "Low"
    elif score < 70:
        return "Moderate"
    return "Critical"


def _action_trigger(level: str) -> str:
    """Map a risk level to a prescriptive action string."""
    return {
        "Low":      "Background logging — no escalation",
        "Moderate": "Assign analyst · SEBI check · draft statement",
        "Critical": "Executive crisis protocol · legal review · PR response",
    }.get(level, "Unknown")


def build_decision_matrix(company_scores: list[dict]) -> pd.DataFrame:
    """
    Convert a list of company score dicts into a TOPSIS decision matrix.

    Each dict must have keys:
      "name", "C1_severity", "C2_reach", "C3_recoverability", "C4_criticality"
    Values should be in [0, 100].
    """
    rows = {}
    for cs in company_scores:
        rows[cs["name"]] = {
            "C1_severity":       cs.get("C1_severity",       0),
            "C2_reach":          cs.get("C2_reach",          0),
            "C3_recoverability": cs.get("C3_recoverability", 0),
            "C4_criticality":    cs.get("C4_criticality",    0),
        }
    df = pd.DataFrame.from_dict(rows, orient="index", columns=CRITERIA)
    return df



def anchored_index(criteria: dict, weights) -> dict:
    """
    Risk index for ONE company against the fixed baseline/crisis profiles.
    Returns index, level, action, distances and per-criterion contribution shares.
    """
    x = np.array([float(criteria.get(c, 0.0)) for c in CRITERIA]) / CRITERION_SCALE
    w = np.asarray(weights, dtype=float)
    v = x * w
    a_pos = BASELINE_PROFILE / CRITERION_SCALE * w
    a_neg = CRISIS_PROFILE / CRITERION_SCALE * w
    d_pos = float(np.sqrt(((v - a_pos) ** 2).sum()))
    d_neg = float(np.sqrt(((v - a_neg) ** 2).sum()))
    cc = float(np.clip(d_pos / (d_pos + d_neg or 1e-9), 0.0, 1.0))
    idx = round(cc * 100, 2)
    sq = (v - a_pos) ** 2
    tot = float(sq.sum()) or 1e-12
    level = _classify_level(idx)
    return {
        "risk_index": idx, "cc": round(cc, 4),
        "d_pos": round(d_pos, 4), "d_neg": round(d_neg, 4),
        "level": level, "action": _action_trigger(level),
        "contributions": {c: round(float(s / tot), 4) for c, s in zip(CRITERIA, sq)},
    }
