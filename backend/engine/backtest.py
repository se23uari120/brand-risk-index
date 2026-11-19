"""
engine/backtest.py
==================
Pilot back-test on documented Indian corporate incidents (report Sec. VII-C
and IX-6), using the full stock + news model.

For each incident in backend/data/incidents.json the company is scored
point-in-time on two days:

  incident : the event day + 4 days (the end of the incident week)
  control  : the same day 60 days earlier (a "normal" period)

Each day is scored exactly like the live index (prices up to that day, the
7 days of headlines before it). The index is compared with simpler methods
computed from the same data:

  stock only       : the same TOPSIS with the news signals set to 0
  news only        : the same TOPSIS with the stock signals set to 0
  sentiment only   : max(0, −mean headline sentiment) × 100
  mention volume   : number of relevant headlines

Metrics:
  pairwise accuracy — share of incidents scored riskier than their control day
  hit rate          — incident day reaches Moderate or High (≥ 30)
  false-alarm rate  — control day reaches Moderate or High (≥ 30)

Go First was never listed, so it is scored on news only. With 12 incidents
this is a small pilot: it shows direction, not statistical significance.
Google News returns at most ~100 headlines per query.
"""

import json
import logging
import threading
from datetime import date, datetime, timedelta, timezone

import numpy as np

from config import (BACKTEST_CONTROL_DAYS, BACKTEST_FILE, BACKTEST_WINDOW_DAYS, INCIDENTS_FILE,
                    LEVEL_THRESHOLDS, NEWS_WINDOW_DAYS)
from engine.assess import end_of_day, level_for, score_headlines
from engine.criteria import news_criteria
from engine.search import score_as_of
from market.symbols import load_watchlist, make_profile
from mcdm.ahp import AHP
from mcdm.topsis import topsis_score
from nlp.news import fetch_company_news

logger = logging.getLogger(__name__)
FLAG = LEVEL_THRESHOLDS["moderate"]
METHODS = ["index", "stockOnly", "newsOnly", "sentimentOnly", "mentionVolume"]
state = {"running": False, "progress": 0, "total": 0, "current": None, "error": None}
_lock = threading.Lock()


def load_incidents() -> list:
    return json.loads(INCIDENTS_FILE.read_text(encoding="utf-8"))["incidents"]


def load_results() -> dict | None:
    return json.loads(BACKTEST_FILE.read_text(encoding="utf-8")) if BACKTEST_FILE.exists() else None


def _profile(inc: dict) -> dict:
    wl = {c["symbol"]: c for c in load_watchlist()["companies"]}
    if inc.get("symbol") in wl:
        return wl[inc["symbol"]]
    p = make_profile(inc.get("symbol") or inc["company"], inc["company"], inc["sector"], inc.get("aliases"))
    if inc.get("query"):
        p["query"] = inc["query"]
    return p


def _summarise(crit, window, weights, as_of_day, stock=None):
    score = topsis_score(crit, weights)[0]
    sents = [a["sentiment"] for a in window]
    out = {
        "asOf": as_of_day.isoformat(),
        "score": round(score, 1), "level": level_for(score),
        "criteria": [round(c, 1) for c in crit],
        "stockOnly": round(topsis_score([*crit[:3], 0, 0], weights)[0], 1),
        "newsOnly": round(topsis_score([0, 0, 0, *crit[3:]], weights)[0], 1),
        "sentimentOnly": round(max(0.0, -float(np.mean(sents))) * 100, 1) if sents else 0.0,
        "mentionVolume": len(window),
        "negative": sum(a["label"] == "negative" for a in window),
        "top": [{"t": a["title"], "s": a["source"], "u": a["url"], "d": a["date"], "sc": round(a["sentiment"], 2),
                 "c": a.get("category")} for a in sorted(window, key=lambda a: a["sentiment"])[:3]],
    }
    if stock:
        out.update({"excess5": stock.get("excess5"), "z5": stock.get("z5"), "close": stock.get("close")})
    return out


def _score_day(profile, listed, as_of_day, period, sentiment, weights):
    if listed:
        rec, _ = score_as_of(profile, as_of_day, sentiment, weights, live=False, n_days=1,
                             news_days=NEWS_WINDOW_DAYS, bootstrap=False, period=period)
        start = as_of_day - timedelta(days=NEWS_WINDOW_DAYS)
        window = [a for a in rec.pop("_window") if start < date.fromisoformat(a["date"]) <= as_of_day]
        return _summarise(rec["criteria"], window, weights, as_of_day, rec["stock"])
    # never listed → news only
    window, _ = fetch_company_news(profile, window=(as_of_day - timedelta(days=NEWS_WINDOW_DAYS - 1), as_of_day))
    score_headlines(window, sentiment)
    c4, c5 = news_criteria(window, end_of_day(as_of_day)) if window else (0.0, 0.0)
    return _summarise([0.0, 0.0, 0.0, c4, c5], window, weights, as_of_day)


def _metrics(rows):
    n = len(rows)
    if not n:
        return {}
    pair = {m: round(sum(r["incident"][m] > r["control"][m] for r in rows) / n, 3) for m in METHODS}
    flagged = ["index", "stockOnly", "newsOnly", "sentimentOnly"]
    listed = [r for r in rows if r["listed"]]
    return {
        "incidents": n, "listed": len(listed), "flagThreshold": FLAG,
        "pairwiseAccuracy": pair,
        "hitRate": {m: round(sum(r["incident"][m] >= FLAG for r in rows) / n, 3) for m in flagged},
        "falseAlarmRate": {m: round(sum(r["control"][m] >= FLAG for r in rows) / n, 3) for m in flagged},
        "mean": {m: {"incident": round(float(np.mean([r["incident"][m] for r in rows])), 1),
                     "control": round(float(np.mean([r["control"][m] for r in rows])), 1)} for m in METHODS},
    }


def run_backtest(sentiment) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        weights = np.array(AHP().compute()["weights"])
        incidents = load_incidents()
        state.update(running=True, progress=0, total=len(incidents), error=None)
        rows = []
        for inc in incidents:
            state["current"] = inc["company"]
            event = date.fromisoformat(inc["date"])
            inc_day = event + timedelta(days=BACKTEST_WINDOW_DAYS - 1)
            ctl_day = inc_day - timedelta(days=BACKTEST_CONTROL_DAYS)
            listed = bool(inc.get("symbol"))
            period = (inc_day - timedelta(days=500), inc_day) if listed else None
            profile = _profile(inc)
            try:
                row = {**inc, "listed": listed,
                       "incident": _score_day(profile, listed, inc_day, period, sentiment, weights),
                       "control": _score_day(profile, listed, ctl_day, period, sentiment, weights)}
                row["detected"] = row["incident"]["score"] >= FLAG
                row["separated"] = row["incident"]["score"] > row["control"]["score"]
                for side in ("incident", "control"):
                    row[side]["index"] = row[side].pop("score")
                rows.append(row)
                logger.info("%-22s incident %5.1f  control %5.1f", inc["company"], row["incident"]["index"], row["control"]["index"])
            except Exception as exc:
                logger.warning("Back-test failed for %s: %s", inc["company"], exc)
            state["progress"] += 1
        out = {"runAt": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
               "sentimentEngine": sentiment.name, "windowDays": BACKTEST_WINDOW_DAYS,
               "controlOffsetDays": BACKTEST_CONTROL_DAYS, "metrics": _metrics(rows), "rows": rows}
        BACKTEST_FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        return {"status": "done", **out}
    except Exception as exc:
        logger.exception("Back-test failed")
        state["error"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        state.update(running=False, current=None)
        _lock.release()
