"""
api.py
======
Optional REST API + local web server for the NSE Brand Risk Monitor.

    pip install -r backend/requirements-api.txt
    python backend/api.py              → dashboard at http://127.0.0.1:8000
                                         interactive API docs at /docs

Endpoints (all read backend/output/latest.json, produced by run_pipeline.py)
  GET  /api/health
  GET  /api/summary                       as-of date, engine, counts per level
  GET  /api/companies?sector=&level=&q=   ranked list (light fields)
  GET  /api/companies/{symbol}            full record incl. headlines & series
  GET  /api/sectors                       average score per sector
  GET  /api/method                        criteria definitions + AHP weights
  POST /api/score-headline {"text": ...}  sentiment of any headline
  POST /api/refresh {"offline": false}    re-run the pipeline now (takes ~2 min)
"""

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import API_HOST, API_PORT, LATEST_FILE, PROJECT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

app = FastAPI(title="NSE Brand Risk Monitor API",
              description="Brand risk index for NSE-listed companies from stock behaviour and news "
                          "(AHP-weighted TOPSIS).", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for folder in ("css", "js"):
    if (PROJECT_DIR / folder).exists():
        app.mount(f"/{folder}", StaticFiles(directory=str(PROJECT_DIR / folder)), name=folder)

LIGHT_FIELDS = ("symbol", "name", "sector", "score", "level", "rank", "change5d", "criteria")


def _data() -> dict:
    if not LATEST_FILE.exists():
        raise HTTPException(503, "No results yet — run: python backend/run_pipeline.py")
    return json.loads(LATEST_FILE.read_text(encoding="utf-8"))


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "hasData": LATEST_FILE.exists()}


@app.get("/api/summary")
def summary():
    d = _data()
    counts = defaultdict(int)
    for c in d["companies"]:
        counts[c["level"]] += 1
    return {"asOf": d["asOf"], "generatedAt": d["generatedAt"], "universe": d["universe"],
            "sentimentEngine": d["sentimentEngine"], "companies": len(d["companies"]),
            "levels": counts, "thresholds": d["thresholds"]}


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
    return {"total": len(rows), "data": [{k: c[k] for k in LIGHT_FIELDS} for c in rows]}


@app.get("/api/companies/{symbol}")
def company(symbol: str):
    for c in _data()["companies"]:
        if c["symbol"].upper() == symbol.upper():
            return c
    raise HTTPException(404, f"{symbol} is not in the watchlist")


@app.get("/api/sectors")
def sectors():
    groups = defaultdict(list)
    for c in _data()["companies"]:
        groups[c["sector"]].append(c["score"])
    out = [{"sector": s, "companies": len(v), "avgScore": round(sum(v) / len(v), 1), "maxScore": max(v)}
           for s, v in groups.items()]
    return sorted(out, key=lambda x: -x["avgScore"])


@app.get("/api/method")
def method():
    d = _data()
    return {"criteria": d["criteria"], "ahp": d["ahp"], "thresholds": d["thresholds"],
            "guidance": d["guidance"]}


@app.post("/api/score-headline")
def score_headline(payload: dict = Body(..., examples=[{"text": "SEBI probes accounting lapses at XYZ Ltd"}])):
    from nlp.sentiment import SentimentEngine
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Provide 'text'")
    eng = SentimentEngine(payload.get("engine", "auto"))
    return {"engine": eng.name, "text": text, **eng.score_batch([text])[0]}


@app.post("/api/refresh")
def refresh(payload: dict = Body(default={}, examples=[{"offline": False}])):
    from engine.risk_scorer import BrandRiskPipeline
    pipe = BrandRiskPipeline(offline=bool(payload.get("offline", False)))
    result = pipe.run()
    pipe.save(export_frontend=True)
    return {"status": "ok", "asOf": result["asOf"], "companies": len(result["companies"]),
            "skipped": result["skipped"]}


if __name__ == "__main__":
    uvicorn.run(app, host=API_HOST, port=API_PORT)
