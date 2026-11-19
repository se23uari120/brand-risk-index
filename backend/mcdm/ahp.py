"""
mcdm/ahp.py
===========
Analytic Hierarchy Process (Saaty, 1980) — turns expert pairwise judgements
("market reaction matters 2× more than news tone") into criterion weights.

Steps
-----
1. Pairwise matrix A (n×n): A[i][j] = how much more important criterion i is
   than j on Saaty's 1–9 scale; A[j][i] = 1 / A[i][j].
2. Weights w = principal eigenvector of A, scaled to sum to 1.
3. λmax = principal eigenvalue (n for a perfectly consistent matrix).
4. Consistency Index  CI = (λmax − n) / (n − 1)
5. Consistency Ratio  CR = CI / RI(n)   — judgements are acceptable if CR < 0.10
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Saaty's Random Index (average CI of random matrices of size n)
RI_TABLE = {1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45}

CRITERIA_KEYS = ["C1", "C2", "C3", "C4", "C5"]

# Rows/cols: C1 Market reaction · C2 Trading stress · C3 Lingering damage ·
#            C4 News tone · C5 Negative coverage
# Judgements: the market's verdict (C1) is the strongest evidence; how negative
# the news is (C4) and whether the damage persists (C3) come next and are
# equally important; stress (C2) and raw negative volume (C5) are supporting.
DEFAULT_PAIRWISE = np.array([
    #  C1    C2    C3    C4    C5
    [1,    3,    2,    2,    3  ],   # C1 Market reaction
    [1/3,  1,    1/2,  1/2,  1  ],   # C2 Trading stress
    [1/2,  2,    1,    1,    2  ],   # C3 Lingering damage
    [1/2,  2,    1,    1,    2  ],   # C4 News tone
    [1/3,  1,    1/2,  1/2,  1  ],   # C5 Negative coverage
], dtype=float)


class AHP:
    def __init__(self, pairwise: np.ndarray = None, keys: list[str] = None):
        self.A = DEFAULT_PAIRWISE if pairwise is None else np.asarray(pairwise, float)
        self.n = self.A.shape[0]
        self.keys = keys or CRITERIA_KEYS[: self.n]
        self._validate()

    def _validate(self):
        if self.A.shape != (self.n, self.n):
            raise ValueError("Pairwise matrix must be square")
        if not np.allclose(self.A * self.A.T, 1.0, atol=1e-9):
            raise ValueError("Pairwise matrix must be reciprocal: A[j][i] = 1 / A[i][j]")

    def compute(self) -> dict:
        eigvals, eigvecs = np.linalg.eig(self.A)
        k = int(np.argmax(eigvals.real))
        w = np.abs(eigvecs[:, k].real)
        w = w / w.sum()
        lam = float(eigvals[k].real)
        ci = (lam - self.n) / (self.n - 1) if self.n > 2 else 0.0
        ri = RI_TABLE.get(self.n, 1.49)
        cr = ci / ri if ri > 0 else 0.0
        if cr >= 0.10:
            logger.warning("AHP consistency ratio %.3f ≥ 0.10 — revise the judgements", cr)
        return {
            "keys": self.keys,
            "matrix": self.A.round(6).tolist(),
            "weights": [round(float(x), 6) for x in w],
            "lambda_max": round(lam, 6),
            "CI": round(ci, 6),
            "RI": ri,
            "CR": round(cr, 6),
            "consistent": cr < 0.10,
        }


def default_weights() -> np.ndarray:
    return np.array(AHP().compute()["weights"])
