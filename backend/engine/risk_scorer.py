"""
engine/risk_scorer.py
=====================
The daily pipeline for the watchlist:

  NSE prices (Yahoo) ──► stock signals ──► C1 C2 C3 ─┐
                                                     ├─► AHP weights ─► TOPSIS ─► Risk Index 0–100
  Google News + outlet feeds ──► relevance filter    │                                  │
      ──► sentiment + issue type ──► C4 C5 ──────────┘                                  ▼
                    history.json (daily track) · latest.json · js/data.js (dashboard)

Every day in the backfill window is scored point-in-time (only prices up to
that day and headlines published up to that day), so the trend line on the
dashboard is what the model would have said on each date. The scoring itself
lives in engine/assess.py and is shared with Company Search and the back-test.

The run also exports, for the dashboard's MCDM and Validation tabs: CRITIC
weights and the sensitivity analysis (mcdm/sensitivity.py), a comparison of
news sources, the sentiment check against human labels, and the latest
back-test results.
"""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from config import (BACKFILL_DAYS, BENCHMARK_NAME, BENCHMARK_SYMBOL, CHART_DAYS, DECAY_HALF_LIFE_HOURS,
                    FRONTEND_DATA_JS, HISTORY_FILE, HISTORY_MAX, LATEST_FILE, LEVEL_GUIDANCE,
                    LEVEL_THRESHOLDS, NEWS_REQUEST_GAP_S, NEWS_WINDOW_DAYS, RECOMPUTE_DAYS,
                    WATCHLIST_FILE)
from engine import backtest, evaluation
from engine.assess import IST, _r, assess_company, level_for, score_headlines  # noqa: F401  (level_for re-exported)
from engine.criteria import CRITERIA
from market.nse_prices import get_prices
from market.stock_signals import log_returns, peer_returns
from mcdm.ahp import AHP
from mcdm.sensitivity import run_mcdm_analysis
from nlp.crisis_classifier import CATEGORIES
from nlp.feeds import fetch_outlet_feeds
from nlp.news import fetch_company_news
from nlp.sentiment import SentimentEngine

logger = logging.getLogger(__name__)


def source_comparison(window_articles: dict[str, list[dict]]) -> list[dict]:
    """Per outlet (top 40): how many relevant headlines it carried this week and how negative they were."""
    stats = defaultdict(lambda: {"headlines": 0, "negative": 0, "positive": 0, "sum": 0.0, "companies": set()})
    for sym, arts in window_articles.items():
        for a in arts:
            st = stats[a["source"]]
            st["headlines"] += 1
            st["negative"] += a["label"] == "negative"
            st["positive"] += a["label"] == "positive"
            st["sum"] += a["sentiment"]
            st["companies"].add(sym)
    rows = [{"outlet": k, "headlines": v["headlines"], "negative": v["negative"], "positive": v["positive"],
             "avgSentiment": round(v["sum"] / v["headlines"], 3), "companies": len(v["companies"])}
            for k, v in stats.items()]
    return sorted(rows, key=lambda r: -r["headlines"])[:40]


class BrandRiskPipeline:
    def __init__(self, offline: bool = False, sentiment: str = "auto", limit: int | None = None,
                 reset_history: bool = False, feeds: bool = True):
        self.offline = offline
        self.reset_history = reset_history
        self.feeds = feeds
        wl = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        self.universe = wl.get("universe", "NSE watchlist")
        self.companies = wl["companies"][:limit] if limit else wl["companies"]
        self.ahp = AHP().compute()
        self.weights = np.array(self.ahp["weights"])
        self.sentiment = SentimentEngine(sentiment)

    # ── history (the long-term track record) ────────────────────────────────
    def _merge_history(self, records: list[dict]) -> dict:
        hist = {"series": {}}
        if HISTORY_FILE.exists() and not self.reset_history:
            hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        series = hist.setdefault("series", {})
        for rec in records:
            stored = series.setdefault(rec["symbol"], {})
            new_dates = sorted(rec["_daily"])
            refresh = set(new_dates[-RECOMPUTE_DAYS:])
            for d in new_dates:
                # past days stay frozen as originally scored; the last few are refreshed
                if d not in stored or d in refresh:
                    stored[d] = round(rec["_daily"][d], 1)
            for d in sorted(stored)[:-HISTORY_MAX]:
                del stored[d]
        hist["updated"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        return hist

    def _evaluation(self) -> dict:
        engines = {"lexicon": SentimentEngine("lexicon")}
        if self.sentiment.name == "finbert":
            engines["finbert"] = self.sentiment
        try:
            return evaluation.metrics(engines)
        except Exception as exc:
            logger.warning("Sentiment evaluation skipped: %s", exc)
            return {"labelled": 0}

    # ── main entry point ────────────────────────────────────────────────────
    def run(self) -> dict:
        today = datetime.now(tz=IST).date()
        now = datetime.now(tz=timezone.utc)
        bench, _ = get_prices(BENCHMARK_SYMBOL, offline=self.offline)

        # 1. prices for everyone first (sector peer returns need the whole panel)
        prices, infos, skipped = {}, {}, []
        for co in self.companies:
            try:
                prices[co["symbol"]], infos[co["symbol"]] = get_prices(co["symbol"], offline=self.offline)
            except Exception as exc:
                skipped.append({"symbol": co["symbol"], "reason": str(exc)})
                logger.warning("%-12s skipped: %s", co["symbol"], exc)
        sectors = {co["symbol"]: co["sector"] for co in self.companies if co["symbol"] in prices}
        peers = peer_returns({s: log_returns(df["adj"]) for s, df in prices.items()}, sectors)
        pool = fetch_outlet_feeds(offline=self.offline) if self.feeds else []

        # 2. score each company (stock signals + news)
        records, windows = [], {}
        todo = [co for co in self.companies if co["symbol"] in prices]
        for i, co in enumerate(todo, 1):
            sym = co["symbol"]
            try:
                articles, stats = fetch_company_news(co, offline=self.offline, outlet_pool=pool)
                if not self.offline:
                    time.sleep(NEWS_REQUEST_GAP_S)
                score_headlines(articles, self.sentiment)
                rec = assess_company(co, prices[sym], infos[sym], peers[sym], bench, articles,
                                     self.weights, today, now, BACKFILL_DAYS)
                rec["news"].update({k: stats[k] for k in ("fetched", "kept", "rejected", "providers")})
                windows[sym] = rec.pop("_window")
                records.append(rec)
                logger.info("[%2d/%d] %-12s score %5.1f  %-8s news %d (neg %d)  %s", i, len(todo), sym,
                            rec["score"], rec["level"], rec["news"]["count7d"], rec["news"]["neg7d"],
                            rec["issue"]["dominant"])
            except Exception as exc:
                skipped.append({"symbol": sym, "reason": str(exc)})
                logger.warning("[%2d/%d] %-12s skipped: %s", i, len(todo), sym, exc)
        if not records:
            raise RuntimeError("No company could be scored")

        # 3. history, ranking and chart series
        hist = self._merge_history(records)
        hist_dates = sorted({d for s in hist["series"].values() for d in s})
        chart_dates = bench.index[-CHART_DAYS:]

        records.sort(key=lambda r: r["score"], reverse=True)
        for rank, rec in enumerate(records, 1):
            rec["rank"] = rank
            s = hist["series"][rec["symbol"]]
            rec["history"] = [s.get(d) for d in hist_dates]
            past = [v for v in rec["history"][:-1] if v is not None]
            rec["change5d"] = _r(rec["score"] - past[-5], 1) if len(past) >= 5 else None
            rec["closes"] = [_r(rec["_closes"].get(d), 2) for d in chart_dates]
            path = rec["_path"]
            rec["specific"] = [_r(path.get(d), 2) if path is not None else None for d in chart_dates]
            del rec["_daily"], rec["_closes"], rec["_path"]

        payload = {
            "generatedAt": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "asOf": chart_dates[-1].date().isoformat(),
            "universe": self.universe,
            "exchange": "NSE",
            "sentimentEngine": self.sentiment.name,
            "thresholds": LEVEL_THRESHOLDS,
            "guidance": LEVEL_GUIDANCE,
            "newsWindowDays": NEWS_WINDOW_DAYS,
            "halfLifeHours": DECAY_HALF_LIFE_HOURS,
            "criteria": CRITERIA,
            "issueCategories": CATEGORIES,
            "ahp": self.ahp,
            "benchmark": {
                "symbol": BENCHMARK_SYMBOL, "name": BENCHMARK_NAME,
                "closes": [_r(x, 2) for x in bench["close"].iloc[-CHART_DAYS:]],
                "ret5": _r(bench["adj"].iloc[-1] / bench["adj"].iloc[-6] - 1, 4),
                "ret20": _r(bench["adj"].iloc[-1] / bench["adj"].iloc[-21] - 1, 4),
            },
            "chartDates": [d.date().isoformat() for d in chart_dates],
            "historyDates": hist_dates,
            "companies": records,
            "skipped": skipped,
            "mcdm": run_mcdm_analysis(records, self.weights),
            "sources": source_comparison(windows),
            "evaluation": self._evaluation(),
            "backtest": backtest.load_results(),
        }
        self.payload, self.history = payload, hist
        return payload

    def save(self, export_frontend: bool = True):
        LATEST_FILE.write_text(json.dumps(self.payload, indent=1, ensure_ascii=False), encoding="utf-8")
        HISTORY_FILE.write_text(json.dumps(self.history, indent=1, sort_keys=True), encoding="utf-8")
        logger.info("Saved %s and %s", LATEST_FILE.name, HISTORY_FILE.name)
        if export_frontend:
            write_frontend_data(self.payload)


def write_frontend_data(payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    FRONTEND_DATA_JS.write_text(
        "// Auto-generated by backend/run_pipeline.py — do not edit by hand.\n"
        f"// Generated {payload['generatedAt']} · data as of NSE close {payload['asOf']}\n"
        f"window.RISK_DATA = {body};\n", encoding="utf-8")
    logger.info("Dashboard data written to %s", FRONTEND_DATA_JS)
