"""
engine/backtest.py
==================
Pilot back-test on documented Indian corporate incidents (report Sec. VII-C
and IX-6).

For each incident, headlines naming the company are fetched from Google News
for two windows of equal length:

  incident window : event date .. event date + 4 days
  control window  : the same 5 days, 60 days earlier

Each window is scored exactly like a live search (FinBERT → Table III
criteria → anchored AHP-TOPSIS). The index is compared with two baselines:

  sentiment-only  : mean FinBERT score (the old severity input), as
                    max(0, −mean) × 100 on a 0–100 scale
  mention volume  : number of headlines naming the company

Metrics:
  pairwise accuracy — share of incidents where the method scores the
                      incident window as riskier than its control window
  hit rate          — incident window reaches Moderate or Critical (≥ 40)
  false alarm rate  — control window reaches Moderate or Critical (≥ 40)

With 12 incidents this is a small pilot; results show direction, not
statistical significance. Google News returns at most ~100 items per query.
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

from config import DATA_DIR, OUTPUT_DIR
from engine.live_scoring import score_company_articles
from nlp.text_ingestion import fetch_company_articles, articles_to_texts
from nlp.crisis_classifier import tag_articles

logger = logging.getLogger(__name__)

INCIDENTS_PATH = DATA_DIR / "incidents.json"
RESULTS_PATH = OUTPUT_DIR / "backtest.json"
WINDOW_DAYS = 5
CONTROL_OFFSET_DAYS = 60
FLAG_THRESHOLD = 40.0

state = {"running": False, "progress": 0, "total": 0, "current": None, "error": None}
_lock = threading.Lock()


def load_incidents() -> list:
    with open(INCIDENTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["incidents"]


def load_results() -> dict | None:
    if RESULTS_PATH.exists():
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _window(start_date):
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=WINDOW_DAYS) - timedelta(seconds=1)
    return start, end


def _score_window(bert, inc, window, weights):
    from engine.risk_scorer import resolve_company   # aliases from the company directory
    known = resolve_company(inc["company"]) or {}
    aliases = known.get("aliases", []) + inc.get("aliases", [])
    company = {"id": "BT", "name": inc["company"], "sector": inc["sector"],
               "aliases": aliases, "search_terms": [inc["company"]] + aliases}
    arts = fetch_company_articles(company, general_pool=None, window=window)
    if not arts:
        return {"articles": 0, "risk_index": 0.0, "level": "Low", "sentiment_only": 0.0,
                "compound": 0.0, "negative_ratio": 0.0, "top": []}
    scores = bert.score_batch(articles_to_texts(arts))
    for a, s in zip(arts, scores):
        a["sentiment"], a["label"] = s.get("score", 0.0), s.get("label", "neutral")
    tag_articles(arts)
    r = score_company_articles(arts, inc["sector"], weights, as_of=window[1], bootstrap=100)
    compound = float(np.mean([a["sentiment"] for a in arts]))
    return {
        "articles": len(arts),
        "risk_index": r["risk_index"], "level": r["level"],
        "ci_low": r["ci_low"], "ci_high": r["ci_high"],
        "C1_severity": r["C1_severity"], "C2_reach": r["C2_reach"],
        "dominant_category": r["dominant_category"],
        "compound": round(compound, 3),
        "sentiment_only": round(max(0.0, -compound) * 100, 1),
        "negative_ratio": r["negative_ratio"],
        "top": [{k: a.get(k) for k in ("title", "outlet", "sentiment", "category", "url", "published")}
                for a in sorted(arts, key=lambda a: a["sentiment"])[:3]],
    }


def _metrics(rows):
    n = len(rows)
    if not n:
        return {}

    def pairwise(key):
        return round(sum(r["incident"][key] > r["control"][key] for r in rows) / n, 3)

    def rate(key, window):
        return round(sum(r[window][key] >= FLAG_THRESHOLD for r in rows) / n, 3)

    return {
        "incidents": n,
        "pairwise_accuracy": {"risk_index": pairwise("risk_index"),
                              "sentiment_only": pairwise("sentiment_only"),
                              "mention_volume": pairwise("articles")},
        "hit_rate": {"risk_index": rate("risk_index", "incident"),
                     "sentiment_only": rate("sentiment_only", "incident")},
        "false_alarm_rate": {"risk_index": rate("risk_index", "control"),
                             "sentiment_only": rate("sentiment_only", "control")},
        "mean": {
            "risk_index": {"incident": round(np.mean([r["incident"]["risk_index"] for r in rows]), 1),
                           "control": round(np.mean([r["control"]["risk_index"] for r in rows]), 1)},
            "sentiment_only": {"incident": round(np.mean([r["incident"]["sentiment_only"] for r in rows]), 1),
                               "control": round(np.mean([r["control"]["sentiment_only"] for r in rows]), 1)},
            "mention_volume": {"incident": round(np.mean([r["incident"]["articles"] for r in rows]), 1),
                               "control": round(np.mean([r["control"]["articles"] for r in rows]), 1)},
        },
        "flag_threshold": FLAG_THRESHOLD,
    }


def run_backtest(bert, weights, scorer_name: str) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        incidents = load_incidents()
        state.update(running=True, progress=0, total=len(incidents), error=None)
        rows = []
        for inc in incidents:
            state["current"] = inc["company"]
            day = datetime.fromisoformat(inc["date"]).date()
            inc_w = _window(day)
            ctl_w = _window(day - timedelta(days=CONTROL_OFFSET_DAYS))
            try:
                row = {**inc,
                       "incident_window": [inc_w[0].date().isoformat(), inc_w[1].date().isoformat()],
                       "control_window": [ctl_w[0].date().isoformat(), ctl_w[1].date().isoformat()],
                       "incident": _score_window(bert, inc, inc_w, weights),
                       "control": _score_window(bert, inc, ctl_w, weights)}
                row["detected"] = row["incident"]["risk_index"] >= FLAG_THRESHOLD
                row["separated"] = row["incident"]["risk_index"] > row["control"]["risk_index"]
                rows.append(row)
            except Exception as exc:  # keep going; record the failure
                logger.warning("Back-test failed for %s: %s", inc["company"], exc)
            state["progress"] += 1
        out = {
            "run_at": datetime.now(tz=timezone.utc).isoformat(),
            "scorer": scorer_name,
            "window_days": WINDOW_DAYS,
            "control_offset_days": CONTROL_OFFSET_DAYS,
            "metrics": _metrics(rows),
            "rows": rows,
        }
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        return {"status": "done", **out}
    except Exception as exc:
        logger.exception("Back-test failed")
        state["error"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        state.update(running=False, current=None)
        _lock.release()
