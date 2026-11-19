"""
engine/risk_scorer.py
=====================
End-to-end pipeline:

  NSE prices (Yahoo) ──► stock signals ──► C1 C2 C3 ─┐
                                                     ├─► AHP weights ─► TOPSIS ─► Risk Index 0–100
  Google News ──► relevance filter ──► sentiment ──► C4 C5 ─┘                         │
                                                                                     ▼
                                     history.json (daily track) · latest.json · js/data.js

Every day in the backfill window is scored point-in-time (only prices up to
that day and headlines published up to that day), so the trend line on the
dashboard is what the model would have said on each date.
"""

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

from config import (BACKFILL_DAYS, BENCHMARK_NAME, BENCHMARK_SYMBOL, CHART_DAYS,
                    FRONTEND_DATA_JS, HISTORY_FILE, HISTORY_MAX, LATEST_FILE,
                    LEVEL_GUIDANCE, LEVEL_THRESHOLDS, NEWS_KEEP_DAYS,
                    NEWS_REQUEST_GAP_S, NEWS_WINDOW_DAYS, RECOMPUTE_DAYS,
                    WATCHLIST_FILE)
from engine.criteria import CRITERIA, news_criteria, stock_criteria
from market.nse_prices import IST, get_prices
from market.stock_signals import compute_stock_signals, log_returns, peer_returns
from mcdm.ahp import AHP
from mcdm.topsis import topsis_score
from nlp.news import fetch_company_news
from nlp.sentiment import SentimentEngine

logger = logging.getLogger(__name__)


def level_for(score: float) -> str:
    if score >= LEVEL_THRESHOLDS["high"]:
        return "High"
    if score >= LEVEL_THRESHOLDS["moderate"]:
        return "Moderate"
    return "Low"


def _r(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if np.isnan(x) else round(x, nd)


class BrandRiskPipeline:
    def __init__(self, offline: bool = False, sentiment: str = "auto",
                 limit: int | None = None, reset_history: bool = False):
        self.offline = offline
        self.reset_history = reset_history
        wl = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        self.universe = wl.get("universe", "NSE watchlist")
        self.companies = wl["companies"][:limit] if limit else wl["companies"]
        self.ahp = AHP().compute()
        self.weights = np.array(self.ahp["weights"])
        self.sentiment = SentimentEngine(sentiment)

    # ── per-company scoring ─────────────────────────────────────────────────
    def _score_company(self, co, prices, info, peer, bench, today):
        signals, path = compute_stock_signals(prices, bench, peer, BACKFILL_DAYS, CHART_DAYS)
        if signals.empty:
            raise RuntimeError("not enough price history")

        articles, news_stats = fetch_company_news(co, offline=self.offline)
        if not self.offline:
            time.sleep(NEWS_REQUEST_GAP_S)
        scored = self.sentiment.score_batch([a["title"] for a in articles]) if articles else []
        for a, s in zip(articles, scored):
            a["sentiment"], a["label"] = s["score"], s["label"]
        art_dates = [date.fromisoformat(a["date"]) for a in articles]

        daily = {}
        last_day = signals.index[-1].date()
        for ts, sig in signals.iterrows():
            d = ts.date()
            # the latest row also counts headlines published after the last close
            end = max(d, today) if d == last_day else d
            start = end - timedelta(days=NEWS_WINDOW_DAYS)
            window = [a for a, ad in zip(articles, art_dates) if start < ad <= end]
            c1, c2, c3 = stock_criteria(sig)
            c4, c5 = news_criteria([a["sentiment"] for a in window], [a["label"] for a in window])
            crit = [c1, c2, c3, c4, c5]
            score, d_pos, d_neg = topsis_score(crit, self.weights)
            daily[d.isoformat()] = {"score": score, "criteria": crit, "dPos": d_pos,
                                    "dNeg": d_neg, "window": window, "sig": sig}

        cur = daily[last_day.isoformat()]
        sig, window = cur["sig"], cur["window"]
        recent_cut = today - timedelta(days=NEWS_KEEP_DAYS)
        return {
            "symbol": co["symbol"],
            "name": co["name"],
            "legalName": info.get("longName"),
            "sector": co["sector"],
            "score": _r(cur["score"], 1),
            "level": level_for(cur["score"]),
            "criteria": [_r(c, 1) for c in cur["criteria"]],
            "topsis": {"dPos": _r(cur["dPos"], 4), "dNeg": _r(cur["dNeg"], 4)},
            "stock": {
                "close": _r(sig["close"], 2),
                "beta": _r(sig["beta"], 2), "betaSector": _r(sig["beta_sector"], 2),
                "hasPeers": peer is not None,
                "ret5": _r(sig["ret5"], 4), "ret20": _r(sig["ret20"], 4),
                "idxRet5": _r(sig["idx_ret5"], 4), "idxRet20": _r(sig["idx_ret20"], 4),
                "peerRet5": _r(sig["peer_ret5"], 4),
                "excess5": _r(sig["excess5"], 4), "excess20": _r(sig["excess20"], 4),
                "z5": _r(sig["z5"], 2), "z20": _r(sig["z20"], 2), "sigma": _r(sig["sigma"], 4),
                "volRatio": _r(sig["vol_ratio"], 2), "volumeRatio": _r(sig["volume_ratio"], 2),
                "abnDrawdown": _r(sig["abn_drawdown"], 4), "ddSigma": _r(sig["dd_sigma"], 2),
                "high52": info.get("fiftyTwoWeekHigh"), "low52": info.get("fiftyTwoWeekLow"),
            },
            "news": {
                "count7d": len(window),
                "neg7d": sum(a["label"] == "negative" for a in window),
                "pos7d": sum(a["label"] == "positive" for a in window),
                "fetched": news_stats.get("fetched", 0),
                "kept": news_stats.get("kept", 0),
                "rejected": news_stats.get("rejected", {}),
                "articles": [
                    {"t": a["title"], "s": a["source"], "u": a["url"], "d": a["date"],
                     "sc": _r(a["sentiment"], 2), "l": a["label"]}
                    for a in articles if date.fromisoformat(a["date"]) > recent_cut
                ][:15],
            },
            "_daily": {d: v["score"] for d, v in daily.items()},
            "_closes": prices["close"],
            "_path": path,
        }

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

    # ── main entry point ────────────────────────────────────────────────────
    def run(self) -> dict:
        today = datetime.now(tz=IST).date()
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

        # 2. score each company (stock signals + news)
        records = []
        todo = [co for co in self.companies if co["symbol"] in prices]
        for i, co in enumerate(todo, 1):
            sym = co["symbol"]
            try:
                rec = self._score_company(co, prices[sym], infos[sym], peers[sym], bench, today)
                records.append(rec)
                logger.info("[%2d/%d] %-12s score %5.1f  %-8s news %d (neg %d)", i, len(todo), sym,
                            rec["score"], rec["level"], rec["news"]["count7d"], rec["news"]["neg7d"])
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
            "criteria": CRITERIA,
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
        }
        self.payload, self.history = payload, hist
        return payload

    def save(self, export_frontend: bool = True):
        LATEST_FILE.write_text(json.dumps(self.payload, indent=1, ensure_ascii=False), encoding="utf-8")
        HISTORY_FILE.write_text(json.dumps(self.history, indent=1, sort_keys=True), encoding="utf-8")
        logger.info("Saved %s and %s", LATEST_FILE.name, HISTORY_FILE.name)
        if export_frontend:
            body = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":"))
            FRONTEND_DATA_JS.write_text(
                "// Auto-generated by backend/run_pipeline.py — do not edit by hand.\n"
                f"// Generated {self.payload['generatedAt']} · data as of NSE close {self.payload['asOf']}\n"
                f"window.RISK_DATA = {body};\n", encoding="utf-8")
            logger.info("Dashboard data written to %s", FRONTEND_DATA_JS)
