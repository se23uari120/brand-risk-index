"""
engine/risk_scorer.py
=====================
Core pipeline orchestrator.

Connects FinBERT NLP output → MCDM criterion scores → AHP weights
→ TOPSIS ranking → final Risk Index per company.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import pandas as pd

from config import DATA_DIR, OUTPUT_DIR, REACH_SCORE, BASE_DIR
from nlp.finbert_pipeline import get_pipeline
from nlp.text_ingestion import (fetch_company_articles, articles_to_texts,
                                 ingest_all_feeds)
from mcdm.ahp import get_default_ahp
from mcdm.topsis import TOPSIS, build_decision_matrix

logger = logging.getLogger(__name__)

FRONTEND_JS_DATA = BASE_DIR.parent / "js" / "data.js"


def _reach_label(article_count: int, negative_ratio: float, default: str = "Low") -> str:
    """Derive reach label from article volume or default."""
    if article_count >= 15 and negative_ratio >= 0.6:
        return "Viral"
    elif article_count >= 8 or negative_ratio >= 0.5:
        return "High"
    elif article_count >= 3:
        return "Medium"
    return default


def build_criterion_scores(company: dict,
                            sentiment_agg: dict,
                            articles: list[dict]) -> dict:
    """
    Convert raw FinBERT output + enterprise metadata into 4 normalised criterion scores [0–100].
    
    C1 (Severity): FinBERT negative sentiment depth & regulatory claim risk.
    C2 (Reach): Audience volume & share velocity.
    C3 (Recoverability): PR turnaround difficulty & historical issue decay.
    C4 (Criticality): Impact on institutional investors, regulators & trust.
    """
    compound = sentiment_agg["compound_score"]
    neg_ratio = sentiment_agg["negative_ratio"]
    count = sentiment_agg["article_count"]

    # Use benchmark values as baseline calibration if available
    b_sent = company.get("benchmark_sentiment")
    if b_sent is not None and abs(compound) < 0.05:
        effective_sentiment = float(b_sent)
    else:
        effective_sentiment = compound

    reach_label = company.get("reach_velocity") or _reach_label(count, neg_ratio)
    dominant_crisis = company.get("crisis_category") or "Operational Scrutiny"

    if articles and not company.get("crisis_category"):
        dominant_crisis = articles[0].get("title", dominant_crisis)[:70]

    # C1: Severity (0-100) - negative sentiment mapped into depth
    # e.g., -0.95 -> 95, -0.10 -> 15
    c1 = float(np.clip(abs(min(0.0, effective_sentiment)) * 100, 5, 100))

    # C2: Reach (0-100)
    c2 = float(REACH_SCORE.get(reach_label, 25))

    # C3: Recoverability (0-100) - proxy based on sentiment depth & reach
    c3 = float(np.clip(0.6 * c1 + 0.4 * c2, 10, 100))

    # C4: Criticality (0-100) - sector sensitivity multiplier * severity
    sector_sensitivity = {
        "Banking & Finance": 1.1,
        "FinTech":           1.15,
        "NBFC":              1.05,
        "Consumer Tech":     0.95,
        "Healthcare":        0.90,
        "Automotive":        0.85,
        "IT Services":       0.75,
        "Telecom":           0.80,
        "Conglomerate":      0.70,
        "Infrastructure":    0.85,
        "Metals & Mining":   0.80,
        "Engineering":       0.70,
        "FMCG":              0.65,
    }
    sens = sector_sensitivity.get(company.get("sector", ""), 0.8)
    c4 = float(np.clip(c1 * sens, 10, 100))

    return {
        "name":               company["name"],
        "id":                 company["id"],
        "sector":             company.get("sector", ""),
        "reach_label":        reach_label,
        "article_count":      count,
        "compound_sentiment": round(effective_sentiment, 2),
        "negative_ratio":     round(neg_ratio, 4),
        "dominant_crisis":    dominant_crisis,
        "action_trigger":     company.get("action_trigger", ""),
        "C1_severity":        round(c1, 2),
        "C2_reach":           round(c2, 2),
        "C3_recoverability":  round(c3, 2),
        "C4_criticality":     round(c4, 2),
    }


class RiskScoringPipeline:
    """
    End-to-end Brand Image Risk Index pipeline.
    """

    def __init__(self, lookback_hours: int = 24, use_mock: bool = False, offline: bool = False):
        self.lookback_hours = lookback_hours
        self.use_mock = use_mock
        self.offline = offline

        registry_path = DATA_DIR / "companies.json"
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.companies = data["companies"]

        self._bert = None

        ahp = get_default_ahp()
        self.ahp_result = ahp.compute()
        self.ahp_weights = np.array(list(self.ahp_result["weights"].values()))

    @property
    def bert(self):
        if self._bert is None:
            self._bert = get_pipeline(use_mock=self.use_mock)
        return self._bert

    def run(self, verbose: bool = True) -> list[dict]:
        logger.info("=" * 60)
        logger.info("Brand Image Risk Index Pipeline — %s",
                    datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        logger.info("=" * 60)

        general_pool = []
        if not self.offline:
            logger.info("Fetching general RSS feeds …")
            general_pool = ingest_all_feeds(lookback_hours=self.lookback_hours)

        criterion_records = []

        for company in self.companies:
            logger.info("Processing: %s", company["name"])

            articles = []
            if not self.offline:
                articles = fetch_company_articles(
                    company,
                    general_pool=general_pool,
                    lookback_hours=self.lookback_hours,
                )

            # If no live articles fetched, use representative crisis headlines
            if not articles:
                sample_h = company.get("sample_headlines", [])
                if sample_h:
                    articles = [{"title": h, "summary": h, "source": "Corporate Risk Monitor"} for h in sample_h]
                else:
                    sample_text = f"{company['name']} operational and regulatory filing updates in {company.get('sector', '')}."
                    articles = [{"title": sample_text, "summary": sample_text, "source": "Internal Monitored Stream"}]

            texts = articles_to_texts(articles)
            scores_list = self.bert.score_batch(texts)
            sentiment_agg = self.bert.aggregate_scores(scores_list)

            crit = build_criterion_scores(company, sentiment_agg, articles)
            criterion_records.append(crit)

            if verbose:
                logger.info(
                    "  Sentiment=%.3f | Articles=%d | "
                    "C1=%.1f C2=%.1f C3=%.1f C4=%.1f",
                    crit["compound_sentiment"],
                    sentiment_agg["article_count"],
                    crit["C1_severity"], crit["C2_reach"],
                    crit["C3_recoverability"], crit["C4_criticality"],
                )

            time.sleep(0.02)

        # Build decision matrix and run TOPSIS
        dm = build_decision_matrix(criterion_records)
        topsis = TOPSIS(dm, self.ahp_weights)
        ranking = topsis.run()

        rank_map = dict(zip(ranking["company"], ranking.to_dict("records")))

        results = []
        for rec in criterion_records:
            rank_row = rank_map.get(rec["name"], {})
            action = rec.get("action_trigger") or rank_row.get("action", "")
            merged = {
                **rec,
                "risk_index": rank_row.get("risk_index", 0.0),
                "level":      rank_row.get("level",      "Low"),
                "action":     action,
                "cc":         rank_row.get("cc",         0.0),
                "d_pos":      rank_row.get("d_pos",      0.0),
                "d_neg":      rank_row.get("d_neg",      0.0),
                "timestamp":  datetime.now(tz=timezone.utc).isoformat(),
                "ahp_weights": self.ahp_result["weights"],
                "ahp_CR":     self.ahp_result["CR"],
            }
            results.append(merged)

        results.sort(key=lambda x: x["risk_index"], reverse=True)
        logger.info("Pipeline complete. %d companies scored.", len(results))
        return results

    def save_results(self, results: list[dict], filename: str = None) -> Path:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        name = filename or f"risk_results_{ts}.json"
        path = OUTPUT_DIR / name

        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        latest_path = OUTPUT_DIR / "latest.json"
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info("Results saved → %s and %s", path, latest_path)
        return path

    def export_to_frontend(self, results: list[dict], js_path: Optional[Path] = None) -> Path:
        target = js_path or FRONTEND_JS_DATA
        target.parent.mkdir(exist_ok=True)

        formatted_companies = []
        for r in results:
            formatted_companies.append({
                "id":        r["id"],
                "name":      r["name"],
                "sector":    r["sector"],
                "risk":      float(r["risk_index"]),
                "level":     r["level"],
                "crisis":    r.get("dominant_crisis", "Operational Scrutiny"),
                "sentiment": float(r["compound_sentiment"]),
                "reach":     r["reach_label"],
                "action":    r["action"]
            })

        sectors_dict = {}
        for c in formatted_companies:
            sec = c["sector"]
            if sec not in sectors_dict:
                sectors_dict[sec] = {"low": 0, "moderate": 0, "critical": 0, "risks": []}
            if c["level"] == "Low":
                sectors_dict[sec]["low"] += 1
            elif c["level"] == "Moderate":
                sectors_dict[sec]["moderate"] += 1
            else:
                sectors_dict[sec]["critical"] += 1
            sectors_dict[sec]["risks"].append(c["risk"])

        formatted_sectors = []
        for sec, val in sectors_dict.items():
            avg_risk = round(sum(val["risks"]) / len(val["risks"]), 1) if val["risks"] else 0.0
            formatted_sectors.append({
                "name": sec,
                "low": val["low"],
                "moderate": val["moderate"],
                "critical": val["critical"],
                "avg": avg_risk
            })

        content = f"""// =============================================
// DATA — Auto-generated by Python AI+MCDM Engine
// Generated: {datetime.now(tz=timezone.utc).isoformat()}
// =============================================

const companies = {json.dumps(formatted_companies, indent=2)};

const sectors = {json.dumps(formatted_sectors, indent=2)};
"""
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Frontend data updated → %s", target)
        return target
