"""
mcdm/ahp.py
===========
Analytic Hierarchy Process (AHP) weight derivation.

Given a pairwise comparison matrix A, computes:
  1. Normalised priority weights  (w_i)
  2. Consistency Index (CI)
  3. Consistency Ratio (CR)  — should be < 0.10

The four criteria for this project are:
  C1 Severity       | C2 Reach | C3 Recoverability | C4 Criticality

Reference:
  Saaty, T. L. (1980). The Analytic Hierarchy Process. McGraw-Hill.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# Random Consistency Index table (Saaty, 1980)
# Index = n - 1  (so RI[3] → n=4 criteria)
RI_TABLE = {1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90,
            5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41}

# ── Default pairwise comparison matrix ───────────────────────────────────────
# Rows/cols: C1 Severity, C2 Reach, C3 Recoverability, C4 Criticality
# Values reflect expert judgment: C1 is most critical, C4 least.
DEFAULT_PAIRWISE = np.array([
    [1,     2,     3,     4   ],   # C1 vs C1, C2, C3, C4
    [1/2,   1,     2,     3   ],   # C2 vs ...
    [1/3,   1/2,   1,     2   ],   # C3 vs ...
    [1/4,   1/3,   1/2,   1   ],   # C4 vs ...
], dtype=float)

CRITERIA_NAMES = ["C1_severity", "C2_reach", "C3_recoverability", "C4_criticality"]


class AHP:
    """
    AHP weight calculator.

    Parameters
    ----------
    pairwise_matrix : square numpy array (n × n) of pairwise ratios.
                      Defaults to the project's expert-defined matrix.
    """

    def __init__(self, pairwise_matrix: np.ndarray = None,
                 criteria_names: list[str] = None):
        self.A = pairwise_matrix if pairwise_matrix is not None else DEFAULT_PAIRWISE
        self.n = self.A.shape[0]
        self.criteria_names = criteria_names or CRITERIA_NAMES[: self.n]

        self.weights:      np.ndarray = None
        self.lambda_max:   float      = None
        self.CI:           float      = None
        self.CR:           float      = None

    # ── Core computation ─────────────────────────────────────────────────────

    def compute(self) -> dict:
        """
        Run AHP and return a result dict with weights and consistency metrics.

        Steps
        -----
        1. Column-normalise the pairwise matrix.
        2. Row-average to get priority weights.
        3. Compute λ_max for consistency checking.
        4. Compute CI = (λ_max − n) / (n − 1).
        5. Compute CR = CI / RI[n].
        """
        # Step 1: column sums → normalise
        col_sums     = self.A.sum(axis=0)              # shape (n,)
        A_norm       = self.A / col_sums               # shape (n, n)

        # Step 2: row means = priority weights
        self.weights = A_norm.mean(axis=1)             # shape (n,)

        # Step 3: λ_max = mean of (A·w / w)
        Aw           = self.A @ self.weights            # shape (n,)
        ratios       = Aw / self.weights
        self.lambda_max = ratios.mean()

        # Step 4 & 5: CI and CR
        self.CI = (self.lambda_max - self.n) / (self.n - 1)
        ri      = RI_TABLE.get(self.n, 1.49)
        self.CR = self.CI / ri if ri > 0 else 0.0

        result = {
            "weights":     dict(zip(self.criteria_names, self.weights.tolist())),
            "lambda_max":  round(float(self.lambda_max), 4),
            "CI":          round(float(self.CI), 4),
            "CR":          round(float(self.CR), 4),
            "CR_acceptable": bool(self.CR < 0.10),
        }

        if not result["CR_acceptable"]:
            logger.warning(
                "AHP Consistency Ratio %.3f >= 0.10 — "
                "pairwise matrix may be inconsistent.", self.CR
            )
        else:
            logger.info(
                "AHP weights computed. CR=%.3f (acceptable). "
                "Weights: %s", self.CR,
                {k: round(v, 4) for k, v in result["weights"].items()}
            )

        return result

    def get_weights_array(self) -> np.ndarray:
        """Return computed weights as a numpy array (compute if needed)."""
        if self.weights is None:
            self.compute()
        return self.weights

    # ── Human-readable summary ───────────────────────────────────────────────

    def summary(self) -> str:
        if self.weights is None:
            self.compute()
        lines = ["AHP Priority Weights", "=" * 40]
        for name, w in zip(self.criteria_names, self.weights):
            lines.append(f"  {name:<22} {w:.4f}  ({w*100:.1f}%)")
        lines += [
            "-" * 40,
            f"  lambda_max  = {self.lambda_max:.4f}",
            f"  CI          = {self.CI:.4f}",
            f"  CR          = {self.CR:.4f}  "
            f"({'OK' if self.CR < 0.10 else 'INCONSISTENT - revise matrix'})",
        ]
        return "\n".join(lines)


# ── Module-level singleton ────────────────────────────────────────────────────

_default_ahp: AHP = None


def get_default_ahp() -> AHP:
    """Return a cached AHP instance with the project's default matrix."""
    global _default_ahp
    if _default_ahp is None:
        _default_ahp = AHP()
        _default_ahp.compute()
    return _default_ahp


def get_default_weights() -> dict:
    """Convenience: return {criterion_name: weight} from the default AHP."""
    return get_default_ahp().compute()["weights"]

