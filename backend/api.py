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
MAX_SEARCHES, REFRESH_ON_VISIT=true|false, STALE_MINUTES.

Public free hosting (render.yaml) runs it with READ_ONLY=true,
LIVE_REFRESH=false and REFRESH_ON_VISIT=true: it starts from the daily job's
results, re-scores the watchlist whenever a dashboard opens and the results
are older than STALE_MINUTES, and answers Company Search. Nobody on the
internet can change files or start other re-runs. Without FinBERT it reuses
the daily run's FinBERT scores for headlines it already saw.
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
                    REFRESH_MINUTES, REFRESH_ON_VISIT, SENTIMENT_CACHE_FILE, STALE_MINUTES)
from engine import backtest as backtest_mod
from engine import evaluation
from engine.refresh import check_refresh
from market.symbols import load_watchlist, resolve, save_watchlist, suggest
from nlp.crisis_classifier import CATEGORIES, classify, regulators_mentioned
from nlp.sentiment import CachedSentiment, SentimentEngine, load_score_cache

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
live = {"running": False, "lastRun": None, "lastError": None, "nextRun": None, "lastAttempt": None,
        "refreshMinutes": REFRESH_MINUTES, "enabled": LIVE_REFRESH,
        "refreshOnVisit": REFRESH_ON_VISIT, "staleMinutes": STALE_MINUTES}
_search_slots = threading.BoundedSemaphore(MAX_SEARCHES)
_visit_lock = threading.Lock()
_file_memo: dict = {}


def engine(name: str = SENTIMENT_MODE) -> SentimentEngine:
    if name not in _engines:
        _engines[name] = SentimentEngine(name)
    return _engines[name]


def _memo(path, read):
    """read(path), re-read only when the file changes (status polls must stay cheap on a small server)."""
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    hit = _file_memo.get(path)
    if not hit or hit[0] != mtime:
        try:
            hit = (mtime, read(path))
        except Exception as exc:
            logger.warning("Could not read %s: %s", path.name, exc)
            hit = (mtime, None)
        _file_memo[path] = hit
    return hit[1]


def _meta() -> dict:
    """generatedAt / asOf / sentiment of the stored results."""
    def read(p):
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"generatedAt": d.get("generatedAt"), "asOf": d.get("asOf"),
                "sentimentEngine": d.get("sentimentEngine"), "sentimentMix": d.get("sentimentMix")}
    return _memo(LATEST_FILE, read) or {}


def _stored_scores() -> dict:
    return _memo(SENTIMENT_CACHE_FILE, lambda p: load_score_cache(p)) or {}


def scorer():
    """Sentiment for a run or a search. Without FinBERT, headlines the daily FinBERT run
    already scored keep that score; only newer ones use the word list."""
    base = engine()
    if base.name == "finbert":
        return base
    stored = _stored_scores()
    return CachedSentiment(base, stored) if stored else base


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
        pipe.sentiment = scorer()                       # reuse the loaded model (and stored FinBERT scores)
        payload = pipe.run()
        old = json.loads(LATEST_FILE.read_text(encoding="utf-8")) if LATEST_FILE.exists() else None
        check_refresh(payload, old, {c["symbol"] for c in load_watchlist()["companies"]})
        pipe.save(export_frontend=True)
        live["lastRun"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        logger.info("Refresh done: %d companies, sentiment %s %s", len(payload["companies"]),
                    payload["sentimentEngine"], payload.get("sentimentMix") or "")
        return {"status": "ok", "asOf": payload["asOf"], "companies": len(payload["companies"])}
    except Exception as exc:
        logger.exception("Pipeline run failed")
        live["lastError"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        live["running"] = False
        _run_lock.release()


def _refresh_if_stale() -> bool:
    """Refresh on visit: start a background re-score when the stored results are older than
    STALE_MINUTES (and no run is going, and the last attempt was not within STALE_MINUTES)."""
    if not REFRESH_ON_VISIT:
        return False
    now = datetime.now(tz=timezone.utc)
    window = timedelta(minutes=STALE_MINUTES)
    with _visit_lock:
        if live["running"]:
            return False
        gen = _meta().get("generatedAt")
        if gen and now - datetime.fromisoformat(gen) < window:
            return False
        if live["lastAttempt"] and now - datetime.fromisoformat(live["lastAttempt"]) < window:
            return False
        live["lastAttempt"] = now.isoformat(timespec="seconds")
        live["running"] = True                 # claimed now, so parallel visits don't start a second run
    threading.Thread(target=run_pipeline, daemon=True, name="visit-refresh").start()
    return True


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
    if REFRESH_ON_VISIT:
        logger.info("Refresh on visit: re-scoring when a dashboard opens and results are older than %.0f min "
                    "(%d stored FinBERT headline scores)", STALE_MINUTES, len(_stored_scores()))
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
            "liveRefresh": LIVE_REFRESH, "refreshOnVisit": REFRESH_ON_VISIT, "staleMinutes": STALE_MINUTES,
            "sentiment": loaded.name if loaded else SENTIMENT_MODE, "storedScores": len(_stored_scores())}


@app.get("/api/data", summary="Everything the dashboard shows (same as js/data.js)")
def data():
    if not LATEST_FILE.exists():
        _data()                                  # raises the 'first run in progress' 503
    return Response(LATEST_FILE.read_bytes(), media_type="application/json")   # served as stored, no re-encoding


@app.get("/api/live/status")
def live_status():
    return {**live, **_meta()}


@app.post("/api/live/visit", summary="Called when a dashboard opens: re-scores in the background "
                                      "if the results are older than STALE_MINUTES (refresh on visit)")
def live_visit():
    started = _refresh_if_stale()
    return {**live_status(), "started": started}


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
        return search_company(q, scorer(), day)
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
