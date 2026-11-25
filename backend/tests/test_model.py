"""
Unit tests for the brand-risk model: AHP, TOPSIS, levels, the five criteria,
the stock-signal model, news relevance and sentiment, the crisis classifier,
CRITIC / sensitivity, the shared company scorer and the sentiment metrics.
No network access is needed. Run from the repository root:

    py -3 -m unittest discover -s backend/tests -v
"""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.assess import assess_company, level_for, score_headlines  # noqa: E402
from engine.criteria import news_criteria, stock_criteria  # noqa: E402
from engine.evaluation import report  # noqa: E402
from market.stock_signals import compute_stock_signals, log_returns  # noqa: E402
from mcdm.ahp import AHP, DEFAULT_PAIRWISE  # noqa: E402
from mcdm.critic import combine_weights, critic_weights  # noqa: E402
from mcdm.sensitivity import indices, run_mcdm_analysis, spearman  # noqa: E402
from mcdm.topsis import TOPSIS, topsis_score  # noqa: E402
from nlp.crisis_classifier import classify, regulators_mentioned  # noqa: E402
from nlp.news import RelevanceFilter, normalise  # noqa: E402
from nlp.sentiment import CachedSentiment, SentimentEngine, lexicon_score  # noqa: E402
from engine.refresh import check_refresh  # noqa: E402

W = np.array(AHP().compute()["weights"])
NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)


def art(score, label, hours_ago=1, title="X news", source="A", category=None):
    pub = NOW - timedelta(hours=hours_ago)
    a = {"title": title, "sentiment": score, "label": label, "source": source, "url": "",
         "published": pub.isoformat(), "date": pub.date().isoformat(), "provider": "google"}
    if category:
        a["category"], a["regulators"] = category, []
    return a


def market(n=320, seed=1, beta=1.0, noise=0.012, shock=None, sector_shock=None):
    """Synthetic stock + NIFTY + peer frames. shock=(days, total_log_return) hits only the stock."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-06-02", periods=n)
    rm = rng.normal(0.0003, 0.009, n)
    rs = rng.normal(0, 0.006, n)                       # sector factor beyond the market
    r = beta * rm + rs + rng.normal(0, noise, n)
    peer = rm + rs + rng.normal(0, 0.004, n)
    if shock:
        days, total = shock
        r[-days:] += total / days
    if sector_shock:
        days, total = sector_shock
        r[-days:] += total / days
        peer[-days:] += total / days
    to_df = lambda x: pd.DataFrame({"close": 100 * np.exp(np.cumsum(x)), "adj": 100 * np.exp(np.cumsum(x)),
                                    "volume": np.full(n, 1e6)}, index=idx)
    return to_df(r), to_df(rm), log_returns(to_df(peer)["adj"])


class TestAHP(unittest.TestCase):
    def test_weights(self):
        res = AHP().compute()
        self.assertAlmostEqual(sum(res["weights"]), 1.0, places=9)
        np.testing.assert_allclose(res["weights"], [0.3689, 0.1093, 0.2063, 0.2063, 0.1093], atol=1e-3)

    def test_consistency(self):
        res = AHP().compute()
        self.assertTrue(res["consistent"])
        self.assertLess(res["CR"], 0.01)
        self.assertGreaterEqual(res["lambda_max"], 5.0)

    def test_eigenvector_matches_power_iteration(self):
        A, w = DEFAULT_PAIRWISE, np.ones(5) / 5
        for _ in range(200):
            w = A @ w
            w /= w.sum()
        np.testing.assert_allclose(w, AHP().compute()["weights"], atol=1e-6)

    def test_rejects_non_reciprocal(self):
        A = DEFAULT_PAIRWISE.copy()
        A[0, 1] = 5
        with self.assertRaises(ValueError):
            AHP(A)


class TestTOPSIS(unittest.TestCase):
    def test_extremes_and_midpoint(self):
        self.assertAlmostEqual(topsis_score([0] * 5, W)[0], 0.0)
        self.assertAlmostEqual(topsis_score([100] * 5, W)[0], 100.0)
        self.assertAlmostEqual(topsis_score([50] * 5, W)[0], 50.0, places=6)

    def test_monotonic_in_every_criterion(self):
        base = [20, 20, 20, 20, 20]
        for j in range(5):
            up = list(base)
            up[j] = 60
            self.assertGreater(topsis_score(up, W)[0], topsis_score(base, W)[0])

    def test_one_severe_signal_not_averaged_away(self):
        s = topsis_score([100, 0, 0, 0, 0], W)[0]
        self.assertGreater(s, W[0] * 100 + 10)        # weighted average would give ~37
        self.assertAlmostEqual(s, 52.8, delta=0.5)

    def test_independent_of_other_companies(self):
        a = TOPSIS(np.array([[40, 10, 20, 0, 0]]), W).run()["score"][0]
        b = TOPSIS(np.array([[40, 10, 20, 0, 0], [100, 100, 100, 100, 100], [0, 0, 0, 0, 0]]), W).run()["score"][0]
        self.assertAlmostEqual(a, b)

    def test_relative_mode_spans_set(self):
        out = TOPSIS(np.array([[10, 10, 10, 10, 10], [50, 50, 50, 50, 50], [90, 90, 90, 90, 90]]), W, mode="relative").run()
        self.assertAlmostEqual(out["score"].min(), 0.0)
        self.assertAlmostEqual(out["score"].max(), 100.0)


class TestLevels(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(level_for(29.9), "Low")
        self.assertEqual(level_for(30), "Moderate")
        self.assertEqual(level_for(49.9), "Moderate")
        self.assertEqual(level_for(50), "High")


class TestStockCriteria(unittest.TestCase):
    sig = dict(z5=0.0, z20=0.0, vol_ratio=1.0, volume_ratio=1.0, car5=-0.01, dd_sigma=0.5)

    def test_market_reaction_scale(self):
        for z, want in [(-1, 0), (-2, 50), (-3, 100), (-5, 100), (1, 0)]:
            self.assertAlmostEqual(stock_criteria({**self.sig, "z5": z})[0], want)

    def test_slow_bleed_uses_month_window(self):
        self.assertAlmostEqual(stock_criteria({**self.sig, "z20": -2})[0], 50)

    def test_trading_stress_damped_when_beating_market(self):
        hot = {**self.sig, "vol_ratio": 2.5, "volume_ratio": 3.0}
        self.assertAlmostEqual(stock_criteria(hot)[1], 100)
        self.assertAlmostEqual(stock_criteria({**hot, "car5": 0.02})[1], 25)

    def test_lingering_damage_scale(self):
        for dd, want in [(0.8, 0), (2, 50), (3, 100)]:
            self.assertAlmostEqual(stock_criteria({**self.sig, "dd_sigma": dd})[2], want)


class TestStockSignals(unittest.TestCase):
    def test_company_specific_drop_is_flagged(self):
        stock, bench, peer = market(shock=(5, -0.15))
        sig, _ = compute_stock_signals(stock, bench, peer, 1, 126)
        self.assertLess(sig["z5"].iloc[-1], -3)
        self.assertLess(sig["excess5"].iloc[-1], -0.10)
        self.assertEqual(stock_criteria(sig.iloc[-1])[0], 100)

    def test_sector_wide_drop_is_not_flagged(self):
        stock, bench, peer = market(sector_shock=(5, -0.15))
        with_peers, _ = compute_stock_signals(stock, bench, peer, 1, 126)
        market_only, _ = compute_stock_signals(stock, bench, None, 1, 126)
        self.assertGreater(with_peers["z5"].iloc[-1], -1.5)          # sector move removed
        self.assertLess(market_only["z5"].iloc[-1], -3)              # NIFTY alone cannot explain it

    def test_point_in_time_history(self):
        stock, bench, peer = market(shock=(5, -0.15))
        sig, path = compute_stock_signals(stock, bench, peer, 30, 126)
        self.assertEqual(len(sig), 30)
        self.assertLess(sig["z5"].iloc[-1], sig["z5"].iloc[0])
        self.assertEqual(len(path), 126)

    def test_recent_listing_is_scored_on_a_shorter_window(self):
        # 111 trading days, like Vedanta Aluminium after its June 2026 demerger
        stock, bench, peer = market(shock=(5, -0.15))
        stock = stock.iloc[-111:]
        sig, _ = compute_stock_signals(stock, bench, peer, 30, 126)
        self.assertEqual(len(sig), 30)
        self.assertTrue((sig["est_days"] < 120).all() and (sig["est_days"] >= 60).all())
        self.assertLess(sig["z5"].iloc[-1], -3)                      # the shock is still caught
        self.assertTrue(np.isfinite(sig[["sigma", "vol_ratio", "dd_sigma"]].to_numpy()).all())


class TestNewsCriteria(unittest.TestCase):
    def test_no_news_is_zero(self):
        self.assertEqual(news_criteria([], NOW), (0.0, 0.0))

    def test_single_headline_is_damped(self):
        c4, c5 = news_criteria([art(-0.9, "negative", 0)], NOW)
        self.assertAlmostEqual(c4, 30.0, places=1)                 # 0.9 / (1 + 2)
        self.assertAlmostEqual(c5, 18.1, places=1)

    def test_neutral_headlines_do_not_dilute_tone(self):
        neg = [art(-0.6, "negative", h) for h in (1, 2, 3)]
        noise = [art(0.0, "neutral", h) for h in range(1, 30)]
        self.assertAlmostEqual(news_criteria(neg, NOW)[0], news_criteria(neg + noise, NOW)[0])

    def test_time_decay(self):
        fresh = news_criteria([art(-0.8, "negative", 1)], NOW)[1]
        old = news_criteria([art(-0.8, "negative", 144)], NOW)[1]
        self.assertGreater(fresh, old * 3)

    def test_positive_news_is_not_risk(self):
        self.assertEqual(news_criteria([art(0.8, "positive", 1)] * 5, NOW), (0.0, 0.0))


class TestRelevanceAndSentiment(unittest.TestCase):
    def test_aliases_exclusions_and_wraps(self):
        f = RelevanceFilter(["State Bank of India", "SBI"], ["SBI Life", "SBI Holdings"])
        self.assertIsNone(f.why_rejected("SBI raises lending rates by 10 bps"))
        self.assertEqual(f.why_rejected("SBI Life posts record premium"), "excluded term")
        self.assertEqual(f.why_rejected("Japan's SBI Holdings to shut crypto unit"), "excluded term")
        self.assertEqual(f.why_rejected("Sensex, Nifty fall as SBI drags"), "market wrap-up")
        self.assertEqual(f.why_rejected("Lisbi village fair begins"), "not about company")

    def test_short_aliases_are_case_sensitive(self):
        f = RelevanceFilter(["ITC"], [])
        self.assertIsNone(f.why_rejected("ITC shares gain after hotel demerger"))
        self.assertEqual(f.why_rejected("Itc-like wording in lowercase itc"), "not about company")

    def test_html_entities_decoded(self):
        self.assertEqual(normalise("Dr. Reddy&amp;#39;s gets USFDA nod"), "Dr. Reddy's gets USFDA nod")

    def test_lexicon(self):
        self.assertEqual(lexicon_score("SEBI probes fraud at the company")["label"], "negative")
        self.assertEqual(lexicon_score("Company bags order win, profit jumps")["label"], "positive")
        self.assertEqual(lexicon_score("4412 put contracts at Rs 1080 strike ahead of expiry")["label"], "neutral")
        self.assertEqual(lexicon_score("Workers go on strike at the plant")["label"], "negative")

    def test_engine_batch(self):
        out = SentimentEngine("lexicon").score_batch(["RBI imposes penalty on bank", "Quarterly results on Friday"])
        self.assertEqual([o["label"] for o in out], ["negative", "neutral"])


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

    def test_leaks_and_crime(self):
        cases = {
            "Gas Leak at ONGC Well in Andhra Pradesh Evacuates 800": "Safety & Product",
            "Leaked documents reveal pricing plan": "Data & Cyber",
            "Customer data leak at app exposes 2 lakh users": "Data & Cyber",
            "Gujarat ATS arrests six for stealing crude oil from ONGC": "Theft & Crime",
            "Madurai Tanishq heist: prime accused arrested": "Theft & Crime",
            "CBI arrests former CEO in loan case": "Fraud & Governance",
        }
        for text, want in cases.items():
            self.assertEqual(classify(text)["category"], want, text)

    def test_regulators(self):
        self.assertEqual(regulators_mentioned("SEBI and RBI act; edits planned"), ["RBI", "SEBI"])


class TestPriceHoles(unittest.TestCase):
    def test_empty_recent_day_rebuilt_from_15_minute_bars(self):
        from market.nse_prices import _to_frame, fill_from_intraday
        day = lambda d, h=9, m=15: int(datetime(2026, 11, d, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30))).timestamp())
        result = {"meta": {"gmtoffset": 19800},
                  "timestamp": [day(17), day(18), day(19), day(20)],
                  "indicators": {"quote": [{"close": [100.0, 101.0, None, 103.0], "volume": [10, 11, None, 13]}],
                                 "adjclose": [{"adjclose": [100.0, 101.0, None, 103.0]}]}}
        intraday = {"timestamp": [day(19, 9, 15), day(19, 15, 0), day(19, 15, 15), day(20, 9, 15)],
                    "indicators": {"quote": [{"close": [101.5, 102.0, 102.4, 103.0], "volume": [3, 4, 5, 6]}]}}
        self.assertEqual(fill_from_intraday(result, intraday), 1)
        df = _to_frame(result)
        row = df.loc[pd.Timestamp("2026-11-19")]
        self.assertAlmostEqual(row["close"], 102.4)               # the day's last 15-minute close
        self.assertAlmostEqual(row["volume"], 12)                 # 3 + 4 + 5
        self.assertAlmostEqual(row["adj"], 102.4)                 # adjustment factor carried forward


class TestCriticAndSensitivity(unittest.TestCase):
    X = np.array([[90, 40, 60, 30, 50], [10, 5, 0, 0, 0], [50, 20, 30, 60, 70], [20, 10, 10, 5, 18],
                  [70, 60, 20, 10, 30], [5, 0, 40, 0, 0]], dtype=float)

    def test_critic(self):
        w = critic_weights(self.X)["weights"]
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertTrue((w > 0).all())

    def test_constant_column_gets_zero_weight(self):
        X = self.X.copy()
        X[:, 1] = 7
        self.assertAlmostEqual(critic_weights(X)["weights"][1], 0.0)

    def test_combine(self):
        np.testing.assert_allclose(combine_weights([0.5, 0.5], [1.0, 0.0], 0.5), [0.75, 0.25])

    def test_spearman(self):
        self.assertAlmostEqual(spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [30, 20, 10]), -1.0)

    def test_indices_match_topsis(self):
        np.testing.assert_allclose(indices(self.X, W), [topsis_score(row, W)[0] for row in self.X], atol=1e-9)

    def test_full_analysis_runs(self):
        recs = [{"symbol": f"S{i}", "criteria": list(row)} for i, row in enumerate(self.X)]
        res = run_mcdm_analysis(recs, W)
        self.assertEqual(len(res["judgements"]), 20)                # 10 judgements × one step down/up
        self.assertEqual(len(res["oneAtATime"]), 30)
        self.assertEqual({c["name"] for c in res["comparison"]}, {"AHP", "CRITIC", "Blend 50/50", "Equal"})
        self.assertEqual(res["comparison"][0]["spearman"], 1.0)    # AHP vs itself
        self.assertGreater(res["monteCarlo"]["spearmanMean"], 0.8)


class TestAssess(unittest.TestCase):
    def test_full_record(self):
        stock, bench, peer = market(shock=(5, -0.12))
        today = stock.index[-1].date()
        now = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12)
        arts = []
        for h, (s, lab, t) in enumerate([(-0.8, "negative", "RBI bars XYZ Bank from issuing cards"),
                                         (-0.6, "negative", "XYZ Bank shares plunge 9% after RBI curbs"),
                                         (0.0, "neutral", "XYZ Bank to hold board meeting"),
                                         (-0.7, "negative", "RBI action on XYZ Bank worries depositors")]):
            pub = now - timedelta(hours=6 * (h + 1))
            arts.append({"title": t, "sentiment": s, "label": lab, "source": "Outlet", "url": "",
                         "published": pub.isoformat(), "date": pub.date().isoformat()})
        score_headlines(arts, SentimentEngine("lexicon"))                # adds categories, keeps scores
        co = {"symbol": "XYZ", "name": "XYZ Bank", "sector": "Financial Services"}
        rec = assess_company(co, stock, {}, peer, bench, arts, W, today, now, n_days=10)
        self.assertEqual(rec["level"], level_for(rec["score"]))
        self.assertGreater(rec["score"], 50)
        self.assertEqual(rec["issue"]["dominant"], "Regulatory Action")
        self.assertIn("RBI", rec["issue"]["regulators"])
        self.assertEqual(len(rec["_daily"]), 10)
        lo, hi = rec["range"]
        self.assertLessEqual(lo, rec["score"] + 1e-6)
        self.assertGreaterEqual(hi, rec["score"] - 1e-6)
        self.assertAlmostEqual(sum(rec["shares"]), 1.0, places=2)


class TestEvaluation(unittest.TestCase):
    def test_report(self):
        r = report(["negative", "neutral", "positive", "negative"], ["negative", "neutral", "neutral", "positive"])
        self.assertAlmostEqual(r["accuracy"], 0.5)
        self.assertEqual(r["confusion"]["positive"]["neutral"], 1)


class TestRefreshOnVisit(unittest.TestCase):
    """A word-list server reuses stored FinBERT scores, and never publishes an incomplete refresh."""

    def test_stored_scores_reused_and_new_headlines_scored(self):
        cs = CachedSentiment(SentimentEngine("lexicon"), {"Known headline": -0.8})
        new = "RBI imposes penalty on XYZ Bank"
        out = cs.score_batch(["Known headline", new])
        self.assertEqual(out[0], {"score": -0.8, "label": "negative"})
        self.assertEqual(out[1]["score"], lexicon_score(new)["score"])
        self.assertEqual(cs.mix(), {"finbert": 1, "lexicon": 1})
        self.assertEqual(cs.label(), "finbert+lexicon")
        self.assertEqual(cs.name, "lexicon")          # engine checks elsewhere still see the word list

    def test_label_names_what_was_actually_used(self):
        self.assertEqual(CachedSentiment(SentimentEngine("lexicon"), {"a": 0.5}).label(), "lexicon")
        cs = CachedSentiment(SentimentEngine("lexicon"), {"a": 0.5})
        cs.score_batch(["a"])
        self.assertEqual(cs.label(), "finbert")

    def test_incomplete_refresh_is_rejected(self):
        def co(sym, google=5):
            return {"symbol": sym, "news": {"providers": {"google": google}}}
        tracked = set("ABCDE")
        old = {"asOf": "2026-11-23", "companies": [co(s) for s in "ABCDE"]}
        check_refresh({"asOf": "2026-11-23", "companies": [co(s) for s in "ABCD"] + [co("E", 0)]}, old, tracked)
        with self.assertRaises(RuntimeError):     # a company could not be scored
            check_refresh({"asOf": "2026-11-23", "companies": [co(s) for s in "ABCD"]}, old, tracked)
        check_refresh({"asOf": "2026-11-23", "companies": [co(s) for s in "ABCD"]}, old, set("ABCD"))  # E was removed
        with self.assertRaises(RuntimeError):     # Google News did not answer
            check_refresh({"asOf": "2026-11-23", "companies": [co(s, 0) for s in "ABCDE"]}, old, tracked)
        with self.assertRaises(RuntimeError):     # prices fell back to an older day
            check_refresh({"asOf": "2026-11-20", "companies": old["companies"]}, old, tracked)


if __name__ == "__main__":
    unittest.main()
