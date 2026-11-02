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
import sys
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

from config import API_HOST, OUTPUT_DIR, DATA_DIR
from mcdm.ahp import get_default_ahp, DEFAULT_PAIRWISE, CRITERIA_NAMES
from nlp.finbert_pipeline import get_pipeline
from engine.risk_scorer import RiskScoringPipeline

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


@app.get("/api/mcdm/ahp", summary="AHP Pairwise Matrix & Weights")
def get_ahp_details():
    ahp = get_default_ahp()
    res = ahp.compute()
    return {
        "pairwise_matrix": DEFAULT_PAIRWISE.tolist(),
        "criteria": CRITERIA_NAMES,
        "weights": res["weights"],
        "consistency_ratio": res["CR"],
        "consistency_index": res["CI"],
        "lambda_max": res["lambda_max"],
        "acceptable": res["CR_acceptable"]
    }


@app.post("/api/score-text", summary="FinBERT Headline Sentiment Scoring")
def score_text(
    payload: dict = Body(..., example={"text": "RBI imposes penalty on digital lending non-compliance", "use_mock": True})
):
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Missing 'text' in request body")

    use_mock = payload.get("use_mock", True)
    bert = get_pipeline(use_mock=use_mock)
    result = bert.score_text(text)
    return {
        "input_text": text,
        "result": result
    }


@app.post("/api/recalculate", summary="Re-run Full Risk Scoring Pipeline")
def recalculate(
    payload: dict = Body(default={}, example={"use_mock": True, "offline": True, "sync_frontend": True})
):
    use_mock = payload.get("use_mock", True)
    offline = payload.get("offline", True)
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
    port = 8000
    logger.info("Starting Brand Image Risk server on http://127.0.0.1:%s", port)
    uvicorn.run("api:app", host="127.0.0.1", port=port, reload=False)
