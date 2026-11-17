"""
api.py
======
FastAPI REST API and Web Server for Brand Image Risk Index.

Features:
  - Serves Interactive Web Dashboard at http://127.0.0.1:8000/
  - Automatic Swagger API docs at http://127.0.0.1:8000/docs
  - REST Endpoints for FinBERT NLP, AHP-TOPSIS MCDM, & Company Comparison
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

# Ensure backend root in path
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import API_HOST, OUTPUT_DIR, DATA_DIR, AHP_WEIGHTS, DECAY_HALF_LIFE_HOURS, SEVERITY_PRIOR
from mcdm.ahp import get_default_ahp, DEFAULT_PAIRWISE, CRITERIA_NAMES
from mcdm.topsis import BASELINE_PROFILE, CRISIS_PROFILE, TOPSIS, build_decision_matrix
from mcdm.critic import critic_weights, combine_weights
from mcdm.sensitivity import run_sensitivity, spearman
from nlp.finbert_pipeline import get_pipeline, FinBERTPipeline
from nlp.crisis_classifier import classify, regulators_mentioned, CATEGORIES
from engine.risk_scorer import (RiskScoringPipeline, SECTOR_SENSITIVITY,
                                 load_registry, save_registry, resolve_company, suggest_companies)
from engine import backtest as backtest_mod
from engine import evaluation as eval_mod
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("api")

app = FastAPI(
    title="AI + MCDM Brand Image Risk Index",
    description="Real-time reputational risk assessment using FinBERT Sentiment NLP and AHP-TOPSIS MCDM weighting engine.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Live feed configuration (env-overridable) ─────────────────
LIVE_FEED        = os.getenv("LIVE_FEED", "true").lower() == "true"
REFRESH_MINUTES  = float(os.getenv("REFRESH_MINUTES", "15"))
LOOKBACK_HOURS   = int(os.getenv("LOOKBACK_HOURS", "48"))
# USE_FINBERT=true loads the ProsusAI/finbert transformer (needs torch);
# otherwise the fast keyword heuristic scorer is used.
USE_FINBERT      = os.getenv("USE_FINBERT", "auto").lower()

def _finbert_available() -> bool:
    try:
        import torch, transformers  # noqa: F401
        return True
    except Exception:
        return False

USE_MOCK_SCORER = not (USE_FINBERT == "true" or (USE_FINBERT == "auto" and _finbert_available()))

_live_lock = threading.Lock()
_live_state = {
    "enabled": LIVE_FEED,
    "running": False,
    "last_run": None,
    "last_error": None,
    "next_run": None,
    "refresh_minutes": REFRESH_MINUTES,
    "lookback_hours": LOOKBACK_HOURS,
    "scorer": "heuristic" if USE_MOCK_SCORER else "finbert",
    "live_companies": 0,
    "total_articles": 0,
}
_live_pipeline = None


def run_live_refresh() -> dict:
    """Fetch live news, score it, run AHP-TOPSIS, and persist results."""
    global _live_pipeline
    if not _live_lock.acquire(blocking=False):
        return {"status": "already_running"}
    _live_state["running"] = True
    try:
        _get_live_pipeline()
        results = _live_pipeline.run(verbose=False)
        _live_pipeline.save_results(results)
        _live_pipeline.export_to_frontend(results)
        _live_state["last_run"] = datetime.now(tz=timezone.utc).isoformat()
        _live_state["last_error"] = None
        _live_state["live_companies"] = sum(1 for r in results if r.get("data_source") == "live")
        _live_state["total_articles"] = sum(int(r.get("article_count", 0)) for r in results if r.get("data_source") == "live")
        _live_state["moneycontrol_articles"] = sum(int(r.get("source_counts", {}).get("moneycontrol", 0)) for r in results if r.get("data_source") == "live")
        _live_state["scorer"] = "heuristic" if _live_pipeline.bert.use_mock else "finbert"
        return {"status": "success", "processed_entities": len(results)}
    except Exception as exc:
        logger.exception("Live refresh failed")
        _live_state["last_error"] = str(exc)
        return {"status": "error", "error": str(exc)}
    finally:
        _live_state["running"] = False
        _live_lock.release()


def _live_loop():
    while True:
        run_live_refresh()
        _live_state["next_run"] = datetime.fromtimestamp(
            time.time() + REFRESH_MINUTES * 60, tz=timezone.utc).isoformat()
        time.sleep(REFRESH_MINUTES * 60)


@app.on_event("startup")
def _start_live_feed():
    if LIVE_FEED:
        logger.info("Live feed enabled: refreshing every %s min (scorer=%s)",
                    REFRESH_MINUTES, _live_state["scorer"])
        threading.Thread(target=_live_loop, daemon=True, name="live-feed").start()


# Mount static CSS & JS folders
css_dir = PROJECT_DIR / "css"
js_dir  = PROJECT_DIR / "js"
if css_dir.exists():
    app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
if js_dir.exists():
    app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")


def _load_latest_results() -> list:
    """Load latest results from output/latest.json or compute fallback."""
    latest_path = OUTPUT_DIR / "latest.json"
    if latest_path.exists():
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error reading %s: %s", latest_path, e)

    pipeline = RiskScoringPipeline(use_mock=True, offline=True)
    results = pipeline.run(verbose=False)
    pipeline.save_results(results)
    return results


@app.get("/", summary="Dashboard Application")
def serve_dashboard():
    """Serves the single-page application dashboard."""
    index_file = PROJECT_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"status": "Dashboard HTML file not found."}, status_code=404)


@app.get("/api/health", summary="Health Check")
def health():
    return {
        "status": "healthy",
        "service": "AI + MCDM Brand Image Risk Index API",
        "finbert_model": "ProsusAI/finbert",
        "ahp_criteria": CRITERIA_NAMES,
        "docs_url": "/docs"
    }


@app.get("/api/companies", summary="List All Monitored Companies")
def get_companies(
    sector: Optional[str] = Query(None, description="Filter by sector name"),
    level: Optional[str] = Query(None, description="Filter by risk level (Low, Moderate, Critical)"),
    q: Optional[str] = Query(None, description="Search company name or ID")
):
    results = _load_latest_results()
    filtered = results

    if sector:
        filtered = [c for c in filtered if c.get("sector") == sector]
    if level:
        filtered = [c for c in filtered if c.get("level") == level]
    if q:
        query_lower = q.lower()
        filtered = [c for c in filtered if query_lower in c.get("name", "").lower() or query_lower in c.get("id", "").lower()]

    return {
        "total": len(filtered),
        "data": filtered
    }


@app.get("/api/companies/{company_id}", summary="Get Single Company Details")
def get_company(company_id: str):
    results = _load_latest_results()
    match = next((c for c in results if c.get("id", "").upper() == company_id.upper()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Company ID '{company_id}' not found")
    return match


@app.get("/api/sectors", summary="Sector Aggregated Risk Summary")
def get_sectors():
    results = _load_latest_results()
    sectors_map = {}
    for c in results:
        sec = c.get("sector", "General")
        if sec not in sectors_map:
            sectors_map[sec] = {"low": 0, "moderate": 0, "critical": 0, "scores": []}
        lvl = c.get("level", "Low")
        if lvl == "Low":
            sectors_map[sec]["low"] += 1
        elif lvl == "Moderate":
            sectors_map[sec]["moderate"] += 1
        else:
            sectors_map[sec]["critical"] += 1
        sectors_map[sec]["scores"].append(float(c.get("risk_index", 0)))

    response = []
    for sec, val in sectors_map.items():
        avg = round(sum(val["scores"]) / len(val["scores"]), 1) if val["scores"] else 0.0
        response.append({
            "name": sec,
            "low": val["low"],
            "moderate": val["moderate"],
            "critical": val["critical"],
            "avg": avg
        })
    response.sort(key=lambda s: s["avg"], reverse=True)
    return response


@app.get("/api/live/status", summary="Live Feed Status")
def live_status():
    return _live_state


@app.post("/api/live/refresh", summary="Fetch Live News Now and Re-score")
def live_refresh():
    return {**run_live_refresh(), "state": _live_state}


@app.get("/api/headlines", summary="Latest Scored Headlines per Company")
def get_headlines(company_id: Optional[str] = Query(None, description="e.g. BR-104")):
    results = _load_latest_results()
    out = [
        {"id": c["id"], "name": c["name"], "source": c.get("data_source", "fallback"),
         "headlines": c.get("headlines", [])}
        for c in results
        if not company_id or c.get("id", "").upper() == company_id.upper()
    ]
    return {"total": len(out), "data": out}


def _get_live_pipeline() -> RiskScoringPipeline:
    global _live_pipeline
    if _live_pipeline is None:
        _live_pipeline = RiskScoringPipeline(
            lookback_hours=LOOKBACK_HOURS, use_mock=USE_MOCK_SCORER, offline=False
        )
    return _live_pipeline


@app.get("/api/sources", summary="News sources in use and their latest article counts")
def list_sources():
    from config import RSS_FEEDS
    from nlp.text_ingestion import INGEST_STATS
    return {
        "rss_outlets": {k: len(v) for k, v in RSS_FEEDS.items()},
        "other": ["Moneycontrol news sitemap", "Moneycontrol via Google News (site:)",
                  "Google News search (all publishers)"],
        "last_fetch_counts": INGEST_STATS,
    }


@app.get("/api/source-matrix", summary="Average sentiment per company per outlet")
def source_matrix(min_articles: int = Query(1, ge=1)):
    """Company x outlet matrix of FinBERT average sentiment, for comparing sources."""
    results = _load_latest_results()
    outlet_tot = {}
    rows = []
    for c in results:
        cells = {}
        for s in c.get("sources", []):
            if s["articles"] >= min_articles:
                cells[s["outlet"]] = {"n": s["articles"], "avg": s["avg_sentiment"],
                                      "neg": s["negative_pct"]}
                t = outlet_tot.setdefault(s["outlet"], {"articles": 0, "companies": 0, "wsum": 0.0, "neg": 0.0})
                t["articles"] += s["articles"]; t["companies"] += 1
                t["wsum"] += s["avg_sentiment"] * s["articles"]; t["neg"] += s["negative_pct"] * s["articles"] / 100
        rows.append({"id": c["id"], "name": c["name"], "risk_index": c.get("risk_index"),
                     "level": c.get("level"), "consensus": c.get("consensus"), "cells": cells})
    outlets = sorted(
        ({"outlet": k, "articles": v["articles"], "companies": v["companies"],
          "avg_sentiment": round(v["wsum"] / v["articles"], 3),
          "negative_pct": round(100 * v["neg"] / v["articles"], 1)}
         for k, v in outlet_tot.items()),
        key=lambda o: (-o["articles"], o["outlet"]))
    return {"outlets": outlets, "companies": rows}


@app.get("/api/sector-list", summary="Sectors with criticality multipliers")
def sector_list():
    return {"sectors": [{"name": k, "sensitivity": v} for k, v in SECTOR_SENSITIVITY.items()],
            "default_sensitivity": 0.8}


@app.get("/api/resolve", summary="Suggest / resolve company names for search")
def resolve(q: str = Query(..., min_length=1)):
    return {"match": resolve_company(q), "suggestions": suggest_companies(q)}


def _parse_day(value: str, end: bool = False) -> datetime:
    try:
        d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Dates must be YYYY-MM-DD, got '{value}'")
    return d.replace(hour=23, minute=59, second=59) if end else d


@app.get("/api/search", summary="Brand-risk assessment for ANY company")
def search_company(
    company: str = Query(..., min_length=2, description="Company name, e.g. 'Swiggy' or 'Nykaa'"),
    sector: Optional[str] = Query(None, description="Optional sector (sets the C4 multiplier); auto-detected for known companies"),
    terms: Optional[str] = Query(None, description="Extra comma-separated keywords / aliases"),
    hours: int = Query(LOOKBACK_HOURS, ge=6, le=720, description="News look-back window in hours"),
    date_from: Optional[str] = Query(None, description="Past window start YYYY-MM-DD (with date_to)"),
    date_to: Optional[str] = Query(None, description="Past window end YYYY-MM-DD"),
):
    """Fetches the company's headlines (live, or for a past date range), scores them
    with FinBERT, builds the four criteria and computes the AHP-TOPSIS Brand Image
    Risk Index on the same fixed scale as the monitored companies."""
    window = None
    if date_from or date_to:
        if not (date_from and date_to):
            raise HTTPException(status_code=400, detail="Give both date_from and date_to")
        window = (_parse_day(date_from), _parse_day(date_to, end=True))
        if window[0] > window[1]:
            raise HTTPException(status_code=400, detail="date_from is after date_to")
        if (window[1] - window[0]).days > 92:
            raise HTTPException(status_code=400, detail="Date range is limited to 92 days")
    pipe = _get_live_pipeline()
    peers = [p for p in _load_latest_results() if p.get("data_source") == "live"] or _load_latest_results()
    extra = [t.strip() for t in (terms or "").split(",") if t.strip()]
    result = pipe.analyze_company(company, sector=sector or "", extra_terms=extra,
                                  peers=peers, lookback_hours=hours, window=window)
    name = result.get("name", company).lower()
    match = next((c for c in load_registry() if c["name"].lower() in (name, company.strip().lower())), None)
    result["on_watchlist"] = bool(match)
    result["watchlist_id"] = match["id"] if match else None
    return result


@app.post("/api/watchlist", summary="Add a company to the monitored watchlist")
def add_to_watchlist(payload: dict = Body(..., examples=[{"name": "Swiggy", "sector": "Consumer Tech", "search_terms": ["Swiggy", "Instamart"]}])):
    name = (payload.get("name") or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Missing company 'name'")
    registry = load_registry()
    existing = next((c for c in registry if c["name"].lower() == name.lower()), None)
    if existing:
        return {"status": "exists", "company": existing}
    nums = [int(c["id"].split("-")[1]) for c in registry if c["id"].startswith("BR-") and c["id"].split("-")[1].isdigit()]
    new = {
        "id": f"BR-{(max(nums) + 1) if nums else 101}",
        "name": name,
        "sector": payload.get("sector") or "General",
        "search_terms": [name] + [t for t in payload.get("search_terms", []) if t and t.lower() != name.lower()],
        "added_by_user": True,
    }
    registry.append(new)
    save_registry(registry)
    threading.Thread(target=run_live_refresh, daemon=True).start()
    return {"status": "added", "company": new, "refreshing": True}


@app.delete("/api/watchlist/{company_id}", summary="Remove a user-added company")
def remove_from_watchlist(company_id: str):
    registry = load_registry()
    match = next((c for c in registry if c["id"].upper() == company_id.upper()), None)
    if not match:
        raise HTTPException(status_code=404, detail="Not found")
    if not match.get("added_by_user"):
        raise HTTPException(status_code=400, detail="Only user-added companies can be removed")
    save_registry([c for c in registry if c is not match])
    threading.Thread(target=run_live_refresh, daemon=True).start()
    return {"status": "removed", "id": match["id"], "refreshing": True}


@app.get("/api/mcdm/ahp", summary="AHP Pairwise Matrix & Weights")
def get_ahp_details():
    ahp = get_default_ahp()
    res = ahp.compute()
    return {
        "pairwise_matrix": DEFAULT_PAIRWISE.tolist(),
        "criteria": CRITERIA_NAMES,
        "weights": res["weights"],
        "config_weights": AHP_WEIGHTS,
        "weights_match_config": all(abs(AHP_WEIGHTS[k] - v) < 5e-4 for k, v in res["weights"].items()),
        "consistency_ratio": res["CR"],
        "consistency_index": res["CI"],
        "lambda_max": res["lambda_max"],
        "acceptable": res["CR_acceptable"],
        "topsis": {"mode": "anchored", "baseline_profile": BASELINE_PROFILE.tolist(),
                   "crisis_profile": CRISIS_PROFILE.tolist()},
        "scoring": {"decay_half_life_hours": DECAY_HALF_LIFE_HOURS, "severity_prior": SEVERITY_PRIOR,
                    "sector_sensitivity": SECTOR_SENSITIVITY},
    }


def _live_records():
    recs = _load_latest_results()
    return [r for r in recs if all(c in r for c in CRITERIA_NAMES)]


@app.get("/api/mcdm/sensitivity", summary="AHP weight / judgement sensitivity and ranking stability")
def mcdm_sensitivity():
    recs = _live_records()
    if len(recs) < 2:
        raise HTTPException(status_code=409, detail="Need at least two scored companies")
    return run_sensitivity(recs, get_default_ahp().get_weights_array())


@app.get("/api/mcdm/weights", summary="AHP vs CRITIC vs combined weights and the resulting ranking")
def mcdm_weights(alpha: float = Query(0.5, ge=0, le=1, description="Share of AHP in the combined weights")):
    recs = _live_records()
    if len(recs) < 2:
        raise HTTPException(status_code=409, detail="Need at least two scored companies")
    X = np.array([[float(r[c]) for c in CRITERIA_NAMES] for r in recs])
    w_ahp = get_default_ahp().get_weights_array()
    cr = critic_weights(X)
    w_cr = cr["weights"]
    w_mix = combine_weights(w_ahp, w_cr, alpha)
    dm = build_decision_matrix(recs)
    out = {}
    for key, w in (("ahp", w_ahp), ("critic", w_cr), ("combined", w_mix)):
        res = TOPSIS(dm, w).run().set_index("company")
        out[key] = {"weights": [round(float(x), 4) for x in w],
                    "index": {n: float(res.loc[n, "risk_index"]) for n in dm.index}}
    names = list(dm.index)
    base = np.array([out["ahp"]["index"][n] for n in names])
    for key in ("critic", "combined"):
        other = np.array([out[key]["index"][n] for n in names])
        out[key]["spearman_vs_ahp"] = round(spearman(base, other), 4)
    return {
        "criteria": CRITERIA_NAMES, "alpha": alpha, "companies": names,
        "critic_detail": {"sigma": [round(float(x), 4) for x in cr["sigma"]],
                          "correlation": [[round(float(v), 3) for v in row] for row in cr["correlation"]]},
        **out,
    }


@app.post("/api/score-text", summary="FinBERT Headline Sentiment Scoring")
def score_text(
    payload: dict = Body(..., example={"text": "RBI imposes penalty on digital lending non-compliance"})
):
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' in request body")

    # Never let this endpoint initialise the shared scorer in heuristic mode
    bert = _heuristic() if payload.get("use_mock") else _get_live_pipeline().bert
    result = bert.score_text(text)
    return {
        "input_text": text,
        "scorer": "heuristic" if bert.use_mock else "finbert",
        "result": result,
        "crisis_category": classify(text),
        "regulators": regulators_mentioned(text),
    }


_heuristic_scorer = None


def _heuristic():
    global _heuristic_scorer
    if _heuristic_scorer is None:
        _heuristic_scorer = FinBERTPipeline(use_mock=True)
    return _heuristic_scorer


# ── Validation: back-test and FinBERT accuracy ───────────────────────────────

@app.get("/api/backtest", summary="Pilot back-test results on documented incidents")
def get_backtest():
    return {"state": backtest_mod.state, "incidents": backtest_mod.load_incidents(),
            "results": backtest_mod.load_results()}


@app.post("/api/backtest/run", summary="Run the incident back-test in the background")
def start_backtest():
    if backtest_mod.state["running"]:
        return {"status": "already_running", "state": backtest_mod.state}
    pipe = _get_live_pipeline()
    scorer = "heuristic" if pipe.bert.use_mock else "finbert"
    threading.Thread(target=backtest_mod.run_backtest, args=(pipe.bert, pipe.ahp_weights, scorer),
                     daemon=True, name="backtest").start()
    return {"status": "started", "state": backtest_mod.state}


def _label_pool():
    pipe = _live_pipeline
    pool = list(getattr(pipe, "last_articles", []) or [])
    if not pool:
        for c in _load_latest_results():
            for h in c.get("headlines", []):
                pool.append({"company": c["name"], "title": h.get("title"), "outlet": h.get("outlet"),
                             "label": h.get("label")})
    return pool


@app.get("/api/eval/sample", summary="Unlabelled headlines to hand-label (model prediction hidden)")
def eval_sample(n: int = Query(15, ge=1, le=50)):
    items = eval_mod.sample(_label_pool(), n)
    return {"items": items, "labelled": len([x for x in eval_mod.load_labels() if x["label"] != "skip"])}


@app.post("/api/eval/label", summary="Store a human sentiment label for a headline")
def eval_label(payload: dict = Body(..., example={"title": "RBI bars ...", "label": "negative"})):
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Missing 'title'")
    try:
        count = eval_mod.add_label(title, payload.get("label", ""), payload.get("company", ""),
                                   payload.get("reviewer", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "saved", "labelled": count}


@app.get("/api/eval/metrics", summary="FinBERT and heuristic accuracy against the human labels")
def eval_metrics():
    return eval_mod.metrics(_get_live_pipeline().bert, _heuristic())


@app.delete("/api/eval/labels", summary="Delete all stored labels")
def eval_clear():
    eval_mod.clear_labels()
    return {"status": "cleared"}


@app.get("/api/crisis-categories", summary="Crisis-event categories used by the classifier")
def crisis_categories():
    return {"categories": CATEGORIES}


@app.post("/api/recalculate", summary="Re-run Full Risk Scoring Pipeline")
def recalculate(
    payload: dict = Body(default={}, example={"use_mock": True, "offline": True, "sync_frontend": True})
):
    use_mock = payload.get("use_mock", USE_MOCK_SCORER)
    offline = payload.get("offline", False)
    sync_frontend = payload.get("sync_frontend", True)

    pipeline = RiskScoringPipeline(use_mock=use_mock, offline=offline)
    results = pipeline.run(verbose=False)
    pipeline.save_results(results)

    if sync_frontend:
        pipeline.export_to_frontend(results)

    return {
        "status": "success",
        "processed_entities": len(results),
        "timestamp": results[0].get("timestamp") if results else None,
        "top_risk": results[0] if results else None
    }


@app.get("/api/compare", summary="Compare Companies Side-by-Side")
def compare_companies(ids: str = Query(..., description="Comma separated IDs, e.g. BR-101,BR-104")):
    target_ids = [i.strip().upper() for i in ids.split(",") if i.strip()]
    if not target_ids:
        raise HTTPException(status_code=400, detail="Please provide ?ids=BR-101,BR-104")

    results = _load_latest_results()
    matched = [c for c in results if c.get("id", "").upper() in target_ids]
    return {
        "count": len(matched),
        "companies": matched
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    # HOST=0.0.0.0 inside a container / on a server; 127.0.0.1 (this PC only) by default
    host = os.getenv("HOST", "127.0.0.1")
    logger.info("Starting Brand Image Risk server on http://%s:%s", host, port)
    uvicorn.run("api:app", host=host, port=port, reload=False)
