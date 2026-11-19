"""
Unit tests for the MCDM engine, band assignment and live scoring.
Run from the repository root:

    py -3 -m unittest discover -s backend/tests -v
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import AHP_WEIGHTS  # noqa: E402
from mcdm.ahp import AHP, CRITERIA_NAMES  # noqa: E402
from mcdm.topsis import (TOPSIS, anchored_index, classify_level, action_for_level,  # noqa: E402
                         BASELINE_PROFILE, CRISIS_PROFILE)
from mcdm.critic import critic_weights, combine_weights  # noqa: E402
from mcdm.sensitivity import spearman, run_sensitivity  # noqa: E402
from nlp.crisis_classifier import classify, regulators_mentioned  # noqa: E402
from engine.live_scoring import score_company_articles, decay_weights  # noqa: E402

W = AHP().get_weights_array()
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def crit(c1, c2, c3, c4):
    return dict(zip(CRITERIA_NAMES, (c1, c2, c3, c4)))


def art(score, label, hours_ago=1, outlet="A", title="X news"):
    return {"title": title, "sentiment": score, "label": label, "outlet": outlet,
            "published": (NOW - timedelta(hours=hours_ago)).isoformat()}


class TestAHP(unittest.TestCase):
    def test_weights_match_report_table_iv(self):
        for got, want in zip(W, [0.4658, 0.2771, 0.1611, 0.0960]):
            self.assertAlmostEqual(got, want, places=3)

    def test_config_weights_match_computed(self):
        for name, w in zip(CRITERIA_NAMES, W):
            self.assertAlmostEqual(AHP_WEIGHTS[name], w, places=3)

    def test_consistency(self):
        r = AHP().compute()
        self.assertAlmostEqual(r["lambda_max"], 4.031, places=2)
        self.assertAlmostEqual(r["CR"], 0.0115, places=3)
        self.assertTrue(r["CR_acceptable"])
        self.assertAlmostEqual(sum(r["weights"].values()), 1.0, places=6)


class TestBands(unittest.TestCase):
    def test_thresholds_table_v(self):
        self.assertEqual(classify_level(39.8), "Low")      # Bharti Airtel case in the report
        self.assertEqual(classify_level(31.2), "Low")      # ITC case in the report
        self.assertEqual(classify_level(40.0), "Moderate")
        self.assertEqual(classify_level(69.99), "Moderate")
        self.assertEqual(classify_level(70.0), "Critical")

    def test_actions(self):
        self.assertIn("no escalation", action_for_level("Low"))
        self.assertIn("SEBI", action_for_level("Moderate"))
        self.assertIn("crisis protocol", action_for_level("Critical"))


class TestTOPSIS(unittest.TestCase):
    def test_anchored_extremes(self):
        self.assertEqual(anchored_index(dict(zip(CRITERIA_NAMES, BASELINE_PROFILE)), W)["risk_index"], 0.0)
        self.assertEqual(anchored_index(dict(zip(CRITERIA_NAMES, CRISIS_PROFILE)), W)["risk_index"], 100.0)

    def test_anchored_monotonic_in_severity(self):
        prev = -1
        for c1 in range(5, 101, 5):
            idx = anchored_index(crit(c1, 50, 0.6 * c1 + 20, max(10, c1)), W)["risk_index"]
            self.assertGreater(idx, prev)
            prev = idx

    def test_anchored_independent_of_peers(self):
        a = crit(60, 75, 66, 60)
        alone = anchored_index(a, W)["risk_index"]
        dm = pd.DataFrame([a, crit(5, 25, 13, 10), crit(95, 100, 97, 100)], index=["a", "lo", "hi"])
        with_peers = TOPSIS(dm, W).run().set_index("company").loc["a", "risk_index"]
        self.assertAlmostEqual(alone, with_peers, places=2)

    def test_relative_mode_spans_set(self):
        dm = pd.DataFrame([crit(10, 25, 16, 10), crit(50, 75, 60, 50), crit(90, 100, 94, 90)],
                          index=["a", "b", "c"])
        r = TOPSIS(dm, W, mode="relative").run().set_index("company")["risk_index"]
        self.assertEqual(r["a"], 0.0)
        self.assertEqual(r["c"], 100.0)

    def test_level_follows_index(self):
        dm = pd.DataFrame([crit(c, 50, 0.6 * c + 20, c) for c in (10, 40, 70, 95)], index=list("abcd"))
        for _, row in TOPSIS(dm, W).run().iterrows():
            self.assertEqual(row["level"], classify_level(row["risk_index"]))


class TestLiveScoring(unittest.TestCase):
    def test_no_negative_news_is_baseline(self):
        r = score_company_articles([art(0.8, "positive"), art(0.0, "neutral")], "FMCG", W, as_of=NOW)
        self.assertEqual(r["C1_severity"], 5.0)
        self.assertEqual(r["level"], "Low")

    def test_single_headline_is_damped(self):
        r = score_company_articles([art(-0.95, "negative")], "FinTech", W, as_of=NOW)
        self.assertLess(r["C1_severity"], 40)   # prior stops one headline dominating

    def test_widespread_negative_coverage_is_critical(self):
        arts = [art(-0.9, "negative", hours_ago=h, outlet=f"O{h % 9}") for h in range(30)]
        r = score_company_articles(arts, "Banking & Finance", W, as_of=NOW)
        self.assertEqual(r["reach_label"], "Viral")
        self.assertEqual(r["level"], "Critical")
        self.assertLessEqual(r["ci_low"], r["risk_index"])
        self.assertGreaterEqual(r["ci_high"], r["risk_index"])

    def test_neutral_articles_do_not_dilute_severity(self):
        base = [art(-0.9, "negative", outlet=f"O{i}") for i in range(6)]
        r1 = score_company_articles([dict(a) for a in base], "IT Services", W, as_of=NOW)
        r2 = score_company_articles([dict(a) for a in base] + [art(0.0, "neutral") for _ in range(30)],
                                    "IT Services", W, as_of=NOW)
        self.assertEqual(r1["C1_severity"], r2["C1_severity"])

    def test_time_decay(self):
        w = decay_weights([art(0, "neutral", 0), art(0, "neutral", 72)], NOW, half_life=72)
        self.assertAlmostEqual(w[0], 1.0, places=3)
        self.assertAlmostEqual(w[1], 0.5, places=3)

    def test_sector_multiplier_affects_c4(self):
        arts = [art(-0.8, "negative", outlet=f"O{i}") for i in range(10)]
        fin = score_company_articles([dict(a) for a in arts], "FinTech", W, as_of=NOW)
        fmcg = score_company_articles([dict(a) for a in arts], "FMCG", W, as_of=NOW)
        self.assertGreater(fin["C4_criticality"], fmcg["C4_criticality"])
        self.assertGreater(fin["risk_index"], fmcg["risk_index"])


class TestCrisisClassifier(unittest.TestCase):
    def test_categories(self):
        cases = {
            "RBI bars Paytm Payments Bank from accepting deposits": "Regulatory Action",
            "ED raids company offices in money laundering probe": "Fraud & Governance",
            "Infosys gets GST notice of Rs 32,000 crore": "Tax Dispute",
            "Delivery partners strike over wages": "Labour & Protest",
            "Company recalls 10,000 scooters over battery fire risk": "Safety & Product",
            "Customer data breach exposes 3 crore records": "Data & Cyber",
            "CEO steps down with immediate effect": "Leadership Change",
            "Shares plunge 8% after weak Q2 guidance": "Market & Earnings",
            "Company opens new office in Pune": "General Coverage",
        }
        for text, want in cases.items():
            self.assertEqual(classify(text)["category"], want, text)

    def test_regulators(self):
        self.assertEqual(regulators_mentioned("SEBI and RBI act; edits planned"), ["RBI", "SEBI"])


class TestCriticAndSensitivity(unittest.TestCase):
    def test_critic(self):
        X = np.array([[10, 25, 16, 10], [50, 75, 60, 40], [80, 50, 70, 90], [30, 100, 58, 20]], float)
        r = critic_weights(X)
        self.assertAlmostEqual(r["weights"].sum(), 1.0, places=6)
        self.assertTrue((r["weights"] >= 0).all())

    def test_constant_column_gets_zero_weight(self):
        X = np.array([[10, 75, 16, 10], [50, 75, 60, 40], [80, 75, 70, 90]], float)
        self.assertAlmostEqual(critic_weights(X)["weights"][1], 0.0, places=6)

    def test_combine(self):
        w = combine_weights([0.5, 0.3, 0.1, 0.1], [0.25, 0.25, 0.25, 0.25])
        self.assertAlmostEqual(w.sum(), 1.0)

    def test_spearman(self):
        self.assertAlmostEqual(spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [30, 20, 10]), -1.0)

    def test_sensitivity_runs(self):
        recs = [{"name": f"c{i}", **crit(10 + 8 * i, 25 + 25 * (i % 4), 30, 10 + 7 * i)} for i in range(8)]
        r = run_sensitivity(recs, W)
        self.assertEqual(len(r["judgements"]), 12)
        self.assertEqual(len(r["one_at_a_time"]), 24)
        self.assertEqual(len(r["monte_carlo"]["companies"]), 8)


if __name__ == "__main__":
    unittest.main()
