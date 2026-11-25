"""
api.py
======
Web server + REST API for the NSE Brand Risk Monitor ("full app").

    setup.bat / ./setup.sh      (once)
    start.bat / ./start.sh      → dashboard at http://127.0.0.1:8000, API docs at /docs

What the server adds to the static dashboard (GitHub Pages):
  • Live mode — re-runs the pipeline every REFRESH_MINUTES (default 60) and the
    open dashboard picks up the new scores automatically
  • Company Search — any NSE-listed company, now or as of a past day
  • Watchlist — add / remove companies (re-scored on the next refresh)
  • Validation — run the back-test, hand-label headlines for the sentiment check,
    score any headline

Environment: HOST, PORT, REFRESH_MINUTES, LIVE_REFRESH=true|false,
SENTIMENT=auto|finbert|lexicon, DECAY_HALF_LIFE_HOURS, READ_ONLY=true|false,
MAX_SEARCHES.

Public free hosting (render.yaml) runs it with READ_ONLY=true and
LIVE_REFRESH=false: it serves the daily job's results from the repo and
answers Company Search, but nobody on the internet can change files or
start long re-runs.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from config import (API_HOST, API_PORT, LATEST_FILE, LIVE_REFRESH, MAX_SEARCHES, PROJECT_DIR, READ_ONLY,
                    REFRESH_MINUTES)
from engine import backtest as backtest_mod
from engine import evaluation
from market.symbols import load_watchlist, resolve, save_watchlist, suggest
from nlp.crisis_classifier import CATEGORIES, classify, regulators_mentioned
from nlp.sentiment import SentimentEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
logger = logging.getLogger("api")
SENTIMENT_MODE = os.getenv("SENTIMENT", "auto")

app = FastAPI(title="NSE Brand Risk Monitor API",
              description="Brand risk index for NSE-listed companies from company-specific stock behaviour "
                          "and news (AHP-weighted TOPSIS over five signals).", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for folder in ("css", "js", "docs"):
    if (PROJECT_DIR / folder).exists():
        app.mount(f"/{folder}", StaticFiles(directory=str(PROJECT_DIR / folder)), name=folder)

# ── shared state ─────────────────────────────────────────────────────────────
_engines: dict[str, SentimentEngine] = {}
_run_lock = threading.Lock()
live = {"running": False, "lastRun": None, "lastError": None, "nextRun": None,
        "refreshMinutes": REFRESH_MINUTES, "enabled": LIVE_REFRESH}
_search_slots = threading.BoundedSemaphore(MAX_SEARCHES)


def engine(name: str = SENTIMENT_MODE) -> SentimentEngine:
    if name not in _engines:
        _engines[name] = SentimentEngine(name)
    return _engines[name]


def _writable():
    """Refuse changes on a public read-only deployment (READ_ONLY=true)."""
    if READ_ONLY:
        raise HTTPException(403, "This public server is read-only: watchlist changes, labelling and re-runs are "
                                 "switched off. Run start.bat on your own computer for those.")


def _data() -> dict:
    if not LATEST_FILE.exists():
        raise HTTPException(503, "No results yet — the first run is in progress (or run: python backend/run_pipeline.py)")
    return json.loads(LATEST_FILE.read_text(encoding="utf-8"))


def run_pipeline() -> dict:
    """Re-score the watchlist now (one run at a time)."""
    if not _run_lock.acquire(blocking=False):
        return {"status": "already_running"}
    live.update(running=True, lastError=None)
    try:
        from engine.risk_scorer import BrandRiskPipeline
        pipe = BrandRiskPipeline(sentiment="lexicon")
        pipe.sentiment = engine()                       # reuse the loaded model
        payload = pipe.run()
        pipe.save(export_frontend=True)
        live["lastRun"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        return {"status": "ok", "asOf": payload["asOf"], "companies": len(payload["companies"])}
    except Exception as exc:
        logger.exception("Pipeline run failed")
        live["lastError"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        live["running"] = False
        _run_lock.release()


def _live_loop():
    if not LATEST_FILE.exists() or time.time() - LATEST_FILE.stat().st_mtime > REFRESH_MINUTES * 60:
        run_pipeline()
    while True:
        live["nextRun"] = (datetime.now(tz=timezone.utc) + timedelta(minutes=REFRESH_MINUTES)).isoformat(timespec="seconds")
        time.sleep(REFRESH_MINUTES * 60)
        run_pipeline()


@app.on_event("startup")
def _startup():
    if READ_ONLY:
        logger.info("Read-only mode: serving stored results and Company Search (sentiment: %s)", SENTIMENT_MODE)
    if LIVE_REFRESH:
        logger.info("Live mode: re-scoring every %.0f minutes (sentiment: %s)", REFRESH_MINUTES, SENTIMENT_MODE)
        threading.Thread(target=_live_loop, daemon=True, name="live-refresh").start()


# ── dashboard & data ─────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)          # the page carries an inline SVG icon


@app.get("/api/health")
def health():
    loaded = _engines.get(SENTIMENT_MODE)        # don't load FinBERT just to answer a health check
    return {"status": "ok", "hasData": LATEST_FILE.exists(), "server": True, "readOnly": READ_ONLY,
            "liveRefresh": LIVE_REFRESH, "sentiment": loaded.name if loaded else SENTIMENT_MODE}


@app.get("/api/data", summary="Everything the dashboard shows (same as js/data.js)")
def data():
    return _data()


@app.get("/api/live/status")
def live_status():
    d = json.loads(LATEST_FILE.read_text(encoding="utf-8")) if LATEST_FILE.exists() else {}
    return {**live, "generatedAt": d.get("generatedAt"), "asOf": d.get("asOf"),
            "sentimentEngine": d.get("sentimentEngine")}


@app.post("/api/live/refresh", summary="Re-score the watchlist now (runs in the background, ~2 min)")
def live_refresh():
    _writable()
    if live["running"]:
        return {"status": "already_running"}
    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"status": "started"}


@app.get("/api/companies")
def companies(sector: str | None = None, level: str | None = None,
              q: str | None = Query(None, description="search name or symbol")):
    rows = _data()["companies"]
    if sector:
        rows = [c for c in rows if c["sector"].lower() == sector.lower()]
    if level:
        rows = [c for c in rows if c["level"].lower() == level.lower()]
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in c["name"].lower() or ql in c["symbol"].lower()]
    keys = ("symbol", "name", "sector", "score", "level", "rank", "change5d", "criteria", "range")
    return {"total": len(rows), "data": [{**{k: c.get(k) for k in keys}, "issue": c["issue"]["dominant"]} for c in rows]}


@app.get("/api/companies/{symbol}")
def company(symbol: str):
    for c in _data()["companies"]:
        if c["symbol"].upper() == symbol.upper():
            return c
    raise HTTPException(404, f"{symbol} is not on the watchlist — try /api/search?q={symbol}")


@app.get("/api/method", summary="Signal definitions, AHP weights, levels")
def method():
    d = _data()
    return {k: d[k] for k in ("criteria", "ahp", "thresholds", "guidance", "halfLifeHours", "newsWindowDays")}


@app.get("/api/mcdm", summary="CRITIC weights and the sensitivity analysis")
def mcdm():
    return _data()["mcdm"]


# ── search & watchlist ───────────────────────────────────────────────────────
@app.get("/api/resolve", summary="Company suggestions for the search box (NSE only)")
def resolve_endpoint(q: str = Query(..., min_length=1)):
    return {"results": suggest(q)}


@app.get("/api/search", summary="Brand-risk assessment for ANY NSE-listed company")
def search(q: str = Query(..., min_length=1, description="name, brand or NSE symbol"),
           as_of: str | None = Query(None, description="past day YYYY-MM-DD; empty = now")):
    from engine.search import search_company
    try:
        day = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        raise HTTPException(400, "as_of must be YYYY-MM-DD")
    if day and day < date(2015, 1, 1):
        raise HTTPException(400, "Choose a date after 2015")
    if not _search_slots.acquire(timeout=90):
        raise HTTPException(503, "The search server is busy with other searches. Try again in a minute.")
    try:
        return search_company(q, engine(), day)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))
    finally:
        _search_slots.release()


@app.get("/api/watchlist")
def watchlist():
    wl = load_watchlist()
    return {"universe": wl.get("universe"),
            "companies": [{k: c.get(k) for k in ("symbol", "name", "sector", "added")} for c in wl["companies"]]}


@app.post("/api/watchlist", summary="Add an NSE company to the watchlist (scored from the next refresh)")
def add_watchlist(payload: dict = Body(..., examples=[{"q": "Swiggy"}])):
    _writable()
    profile = resolve(payload.get("q") or payload.get("symbol") or "")
    if not profile:
        raise HTTPException(404, "No NSE-listed company found")
    wl = load_watchlist()
    if any(c["symbol"] == profile["symbol"] for c in wl["companies"]):
        return {"status": "exists", "symbol": profile["symbol"]}
    entry = {k: profile[k] for k in ("symbol", "name", "sector", "query", "aliases", "exclude")}
    entry["added"] = datetime.now(tz=timezone.utc).date().isoformat()
    wl["companies"].append(entry)
    save_watchlist(wl)
    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"status": "added", "company": entry}


@app.delete("/api/watchlist/{symbol}", summary="Remove a company you added")
def remove_watchlist(symbol: str):
    _writable()
    wl = load_watchlist()
    hit = next((c for c in wl["companies"] if c["symbol"].upper() == symbol.upper()), None)
    if not hit:
        raise HTTPException(404, "Not on the watchlist")
    if not hit.get("added"):
        raise HTTPException(400, f"{hit['name']} is part of the {wl.get('universe')} universe; edit watchlist.json to remove it")
    wl["companies"] = [c for c in wl["companies"] if c is not hit]
    save_watchlist(wl)
    threading.Thread(target=run_pipeline, daemon=True).start()
    return {"status": "removed"}


# ── validation ───────────────────────────────────────────────────────────────
@app.get("/api/backtest")
def get_backtest():
    return {"results": backtest_mod.load_results(), "state": backtest_mod.state}


@app.post("/api/backtest/run", summary="Re-run the 12-incident back-test in the background (~3 min)")
def run_backtest():
    _writable()
    if backtest_mod.state["running"]:
        return {"status": "already_running"}

    def job():
        res = backtest_mod.run_backtest(engine())
        if res.get("status") == "done" and LATEST_FILE.exists():
            from engine.risk_scorer import write_frontend_data
            payload = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
            payload["backtest"] = {k: v for k, v in res.items() if k != "status"}
            LATEST_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
            write_frontend_data(payload)
    threading.Thread(target=job, daemon=True).start()
    return {"status": "started"}


def _label_pool() -> list:
    pool = []
    for c in _data()["companies"]:
        for a in c["news"]["articles"]:
            pool.append({"title": a["t"], "label": a["l"], "company": c["name"], "outlet": a["s"]})
    return pool


@app.get("/api/eval/sample", summary="Unlabelled headlines to hand-label (model prediction hidden)")
def eval_sample(n: int = Query(15, ge=1, le=50)):
    return {"items": evaluation.sample(_label_pool(), n),
            "labelled": len([x for x in evaluation.load_labels() if x["label"] != "skip"])}


@app.post("/api/eval/label", summary="Store a human sentiment label for a headline")
def eval_label(payload: dict = Body(..., examples=[{"title": "RBI bars ...", "label": "negative"}])):
    _writable()
    try:
        n = evaluation.add_label(payload.get("title", ""), payload.get("label", ""), payload.get("company", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"labelled": n}


@app.get("/api/eval/metrics", summary="Accuracy of each sentiment engine against the human labels")
def eval_metrics():
    engines = {"lexicon": engine("lexicon")}
    if engine().name == "finbert":
        engines["finbert"] = engine()
    return evaluation.metrics(engines)


@app.delete("/api/eval/labels", summary="Delete all stored labels")
def eval_clear():
    _writable()
    evaluation.clear_labels()
    return {"status": "cleared"}


@app.post("/api/score-headline", summary="Sentiment, issue type and regulators for any headline")
def score_headline(payload: dict = Body(..., examples=[{"text": "SEBI probes accounting lapses at XYZ Ltd"}])):
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Provide 'text'")
    eng = engine()
    c = classify(text)
    return {"engine": eng.name, "text": text, **eng.score_batch([text])[0],
            "category": c["category"], "keyword": c["keyword"], "regulators": regulators_mentioned(text)}


@app.get("/api/crisis-categories")
def crisis_categories():
    return {"categories": CATEGORIES}


if __name__ == "__main__":
    print(f"Dashboard: http://{'127.0.0.1' if API_HOST == '0.0.0.0' else API_HOST}:{API_PORT}   API docs: /docs")
    uvicorn.run(app, host=API_HOST, port=API_PORT)
