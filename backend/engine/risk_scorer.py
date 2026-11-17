"""
engine/risk_scorer.py
=====================
Core pipeline orchestrator.

Connects FinBERT NLP output → MCDM criterion scores → AHP weights
→ TOPSIS ranking → final Risk Index per company.
"""

import json
import logging
import re
import time
from collections import Counter
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
from engine.live_scoring import score_company_articles

logger = logging.getLogger(__name__)

FRONTEND_JS_DATA = BASE_DIR.parent / "js" / "data.js"


from config import SECTOR_SENSITIVITY  # noqa: E402  (re-exported for api.py)


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
                            articles: list[dict],
                            live: bool = False) -> dict:
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

    if live:
        # Live mode: everything is derived from the fetched news, not the
        # static benchmark profile in companies.json.
        effective_sentiment = compound
        reach_label = _reach_label(count, neg_ratio)
        dominant_crisis = "No significant adverse coverage"
        negatives = [a for a in articles if a.get("sentiment", 0) < 0]
        if negatives:
            worst = min(negatives, key=lambda a: a.get("sentiment", 0))
            dominant_crisis = worst.get("title", dominant_crisis)[:90]
    else:
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
    sens = SECTOR_SENSITIVITY.get(company.get("sector", ""), 0.8)
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
        "action_trigger":     "" if live else company.get("action_trigger", ""),
        "C1_severity":        round(c1, 2),
        "C2_reach":           round(c2, 2),
        "C3_recoverability":  round(c3, 2),
        "C4_criticality":     round(c4, 2),
    }


def compare_sources(articles: list[dict]) -> list[dict]:
    """
    Group FinBERT-scored articles by outlet and summarise each outlet's view.
    Sorted by coverage (most articles first), then by average sentiment.
    """
    groups: dict = {}
    for a in articles:
        groups.setdefault(a.get("outlet") or a.get("source") or "Unknown", []).append(a)

    out = []
    for outlet, arts in groups.items():
        n = len(arts)
        sents = [float(a.get("sentiment", 0.0)) for a in arts]
        labels = Counter(a.get("label", "neutral") for a in arts)
        worst = min(arts, key=lambda a: a.get("sentiment", 0.0))
        best = max(arts, key=lambda a: a.get("sentiment", 0.0))
        out.append({
            "outlet":        outlet,
            "providers":     sorted({a.get("provider", "rss") for a in arts}),
            "articles":      n,
            "avg_sentiment": round(sum(sents) / n, 3),
            "negative_pct":  round(100 * labels.get("negative", 0) / n, 1),
            "neutral_pct":   round(100 * labels.get("neutral", 0) / n, 1),
            "positive_pct":  round(100 * labels.get("positive", 0) / n, 1),
            "most_negative": {k: worst.get(k) for k in ("title", "url", "sentiment")},
            "most_positive": {k: best.get(k) for k in ("title", "url", "sentiment")},
        })
    out.sort(key=lambda s: (-s["articles"], s["avg_sentiment"]))
    return out


def source_consensus(sources: list[dict], min_articles: int = 2) -> dict:
    """How far do outlets agree? Spread = std-dev of per-outlet average sentiment."""
    solid = [s for s in sources if s["articles"] >= min_articles]
    if len(solid) < 2:
        return {"outlets_compared": len(solid), "spread": None, "agreement": "Not enough sources"}
    vals = np.array([s["avg_sentiment"] for s in solid])
    spread = float(np.std(vals))
    agreement = "High" if spread < 0.15 else "Mixed" if spread < 0.35 else "Conflicting"
    most_neg = min(solid, key=lambda s: s["avg_sentiment"])
    most_pos = max(solid, key=lambda s: s["avg_sentiment"])
    return {
        "outlets_compared": len(solid),
        "spread": round(spread, 3),
        "agreement": agreement,
        "mean_of_outlets": round(float(vals.mean()), 3),
        "most_negative_outlet": most_neg["outlet"],
        "most_positive_outlet": most_pos["outlet"],
    }


REGISTRY_PATH = DATA_DIR / "companies.json"


def load_registry() -> list[dict]:
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["companies"]


def save_registry(companies: list[dict]) -> None:
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"companies": companies}, f, indent=2, ensure_ascii=False)


DIRECTORY_PATH = DATA_DIR / "company_directory.json"
_directory_cache: list = []


def load_directory() -> list[dict]:
    global _directory_cache
    if not _directory_cache and DIRECTORY_PATH.exists():
        with open(DIRECTORY_PATH, "r", encoding="utf-8") as f:
            _directory_cache = json.load(f)["companies"]
    return _directory_cache


def _norm(s: str) -> str:
    s = re.sub(r"\s*\(.*?\)", "", s or "")
    s = re.sub(r"\b(ltd\.?|limited|inc\.?|corp\.?)$", "", s.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9&]+", " ", s.lower()).strip()


def _candidates():
    """(display name, sector, aliases, origin) for monitored + directory companies."""
    for c in load_registry():
        yield c["name"], c.get("sector", ""), [t for t in c.get("search_terms", []) if t], "monitored"
    for c in load_directory():
        yield c["name"], c.get("sector", ""), c.get("aliases", []), "directory"


def directory_entry(name: str) -> Optional[dict]:
    """Company-directory record for a name (by name or alias), if any."""
    q = _norm(name)
    for c in load_directory():
        if q == _norm(c["name"]) or q in {_norm(a) for a in c.get("aliases", [])}:
            return c
    return None


def resolve_company(query: str) -> Optional[dict]:
    """
    Match a typed name to a known company (monitored list first, then the
    directory) by name or alias, so a search gets the right sector and the
    aliases headlines use (e.g. 'HUL' for Hindustan Unilever).
    """
    q = _norm(query)
    if not q:
        return None
    for name, sector, aliases, origin in _candidates():
        if q == _norm(name) or q in {_norm(a) for a in aliases}:
            # Monitored companies' search_terms are crisis phrases; use the
            # directory's neutral aliases for searching instead.
            if origin == "monitored":
                entry = directory_entry(name) or directory_entry(re.sub(r"\s*\(.*?\)", "", name)) or {}
                aliases = entry.get("aliases", [])
            return {"name": name, "sector": sector, "aliases": aliases, "origin": origin}
    return None


def suggest_companies(query: str, limit: int = 8) -> list[dict]:
    q = _norm(query)
    if not q:
        return []
    out, seen = [], set()
    for name, sector, aliases, origin in _candidates():
        keys = [_norm(name)] + [_norm(a) for a in aliases]
        if any(k.startswith(q) or f" {q}" in f" {k}" for k in keys) and name.lower() not in seen:
            seen.add(name.lower())
            out.append({"name": name, "sector": sector, "origin": origin})
    out.sort(key=lambda c: (not _norm(c["name"]).startswith(q), c["origin"] != "monitored", c["name"]))
    return out[:limit]


class RiskScoringPipeline:
    """
    End-to-end Brand Image Risk Index pipeline.
    """

    def __init__(self, lookback_hours: int = 24, use_mock: bool = False, offline: bool = False):
        self.lookback_hours = lookback_hours
        self.use_mock = use_mock
        self.offline = offline

        self.companies = load_registry()
        self.general_pool: list = []
        self.general_pool_ts: float = 0.0
        self.last_articles: list = []

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

        self.companies = load_registry()
        general_pool = []
        if not self.offline:
            logger.info("Fetching general RSS feeds …")
            general_pool = ingest_all_feeds(lookback_hours=self.lookback_hours)
            self.general_pool = general_pool
            self.general_pool_ts = time.time()

        criterion_records = []
        self.last_articles = []

        for company in self.companies:
            logger.info("Processing: %s", company["name"])

            articles = []
            if not self.offline:
                entry = (directory_entry(company["name"])
                         or directory_entry(re.sub(r"\s*\(.*?\)", "", company["name"])) or {})
                articles = fetch_company_articles(
                    {**company, "aliases": entry.get("aliases", [])},
                    general_pool=general_pool,
                    lookback_hours=self.lookback_hours,
                )
            is_live = bool(articles)

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
            for art, sc in zip(articles, scores_list):
                art["sentiment"] = sc.get("score", 0.0)
                art["label"] = sc.get("label", "neutral")

            if is_live:
                # Live: Table III criteria from the scored news (time-decayed),
                # plus confidence interval, crisis categories and explanation.
                live = score_company_articles(articles, company.get("sector", ""), self.ahp_weights)
                crit = {
                    "name": company["name"], "id": company["id"], "sector": company.get("sector", ""),
                    "action_trigger": "",
                    **{k: v for k, v in live.items()
                       if k not in ("risk_index", "level", "action", "cc", "d_pos", "d_neg", "contributions")},
                }
                for a in articles:
                    self.last_articles.append({"company": company["name"], "title": a.get("title"),
                                               "outlet": a.get("outlet"), "label": a.get("label"),
                                               "sentiment": a.get("sentiment")})
            else:
                crit = build_criterion_scores(company, sentiment_agg, articles, live=False)
            crit["data_source"] = "live" if is_live else "fallback"
            crit["source_counts"] = dict(Counter(a.get("provider", "sample") for a in articles))
            if is_live:
                crit["sources"] = compare_sources(articles)
                crit["consensus"] = source_consensus(crit["sources"])
            crit["headlines"] = [
                {k: a.get(k) for k in ("title", "source", "outlet", "provider", "url", "published",
                                       "sentiment", "label", "category", "severity_share")}
                for a in sorted(articles, key=lambda a: a.get("sentiment", 0))[:8]
            ]
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
        contrib = topsis.contributions().to_dict("index")

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
                "contributions": {k: round(v, 4) for k, v in contrib.get(rec["name"], {}).items()},
                "topsis_mode": "anchored",
            }
            results.append(merged)
        # rank by index (1 = highest risk)
        for i, r in enumerate(sorted(results, key=lambda x: -x["risk_index"]), start=1):
            r["rank"] = i

        results.sort(key=lambda x: x["risk_index"], reverse=True)
        logger.info("Pipeline complete. %d companies scored.", len(results))
        return results

    def analyze_company(self, name: str, sector: str = "",
                        extra_terms: Optional[list] = None,
                        peers: Optional[list] = None,
                        lookback_hours: Optional[int] = None,
                        window: Optional[tuple] = None) -> dict:
        """
        Brand-risk assessment for ANY company.

        Fetches its news (live, or a past date range via `window=(start, end)`),
        scores every headline with FinBERT, builds the four Table III criteria
        and computes the AHP-TOPSIS index against the fixed baseline/crisis
        profiles, so the result is on the same scale as the monitored companies.
        """
        typed = name.strip()
        known = resolve_company(typed)
        display = known["name"] if known else typed
        sector = sector or (known or {}).get("sector") or ""
        aliases = [a for a in (known or {}).get("aliases", []) if a]
        user_terms = [t for t in (extra_terms or []) if t]
        company = {
            "id": "SEARCH",
            "name": display,
            "sector": sector or "General",
            "aliases": aliases + user_terms,
            "search_terms": [display] + aliases + user_terms,
        }

        live_window = window is None
        if live_window and not self.offline and time.time() - self.general_pool_ts > 900:
            self.general_pool = ingest_all_feeds(lookback_hours=self.lookback_hours)
            self.general_pool_ts = time.time()

        lookback = lookback_hours or self.lookback_hours
        articles = fetch_company_articles(company, general_pool=self.general_pool if live_window else None,
                                          lookback_hours=lookback, window=window)
        as_of = window[1] if window else datetime.now(tz=timezone.utc)
        period = ({"from": window[0].date().isoformat(), "to": window[1].date().isoformat()}
                  if window else {"hours": lookback})
        base = {"name": display, "query": typed, "sector": company["sector"],
                "resolved": known, "search_terms": company["search_terms"],
                "lookback_hours": lookback, "period": period}
        if not articles:
            when = (f"between {period['from']} and {period['to']}" if window
                    else f"in the last {lookback} hours")
            return {"found": False, **base, "article_count": 0,
                    "message": f"No headlines naming '{display}' were found {when}."}

        scores_list = self.bert.score_batch(articles_to_texts(articles))
        for art, sc in zip(articles, scores_list):
            art["sentiment"] = sc.get("score", 0.0)
            art["label"] = sc.get("label", "neutral")

        live = score_company_articles(articles, company["sector"], self.ahp_weights, as_of=as_of)

        # Position among the monitored companies (same anchored scale)
        peer_recs = [p for p in (peers or []) if p.get("name", "").lower() != display.lower()]
        higher = sum(1 for p in peer_recs if float(p.get("risk_index", 0)) > live["risk_index"])

        # Per-outlet view: what does each source say about this company?
        sources = compare_sources(articles)
        for src in sources:
            if src["articles"] < 2:
                src["risk_index"] = None   # too little coverage for a stable score
                src["level"] = None
                continue
            subset = [a for a in articles if (a.get("outlet") or a.get("source") or "Unknown") == src["outlet"]]
            sub = score_company_articles([dict(a) for a in subset], company["sector"], self.ahp_weights,
                                         as_of=as_of, bootstrap=0)
            src["risk_index"] = sub["risk_index"]
            src["level"] = sub["level"]
            src["reach"] = sub["C2_reach"]
            src["severity"] = sub["C1_severity"]

        return {
            "found": True,
            **base,
            **live,
            "id": "SEARCH",
            "rank": higher + 1,
            "ranked_among": len(peer_recs) + 1,
            "peer_avg": round(sum(float(p.get("risk_index", 0)) for p in peer_recs) / len(peer_recs), 1)
                        if peer_recs else None,
            "source_counts": dict(Counter(a.get("provider", "rss") for a in articles)),
            "data_source": "live" if live_window else "historical",
            "scorer": "heuristic" if self.bert.use_mock else "finbert",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "sources": sources,
            "consensus": source_consensus(sources),
            "ahp_weights": self.ahp_result["weights"],
            # Every headline (most negative first) so each source can be inspected
            "headlines": [
                {k: a.get(k) for k in ("title", "source", "outlet", "provider", "url", "published",
                                       "sentiment", "label", "category", "regulators", "weight",
                                       "severity_share")}
                for a in sorted(articles, key=lambda a: a.get("sentiment", 0))[:250]
            ],
        }

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
                "action":    r["action"],
                "source":    r.get("data_source", "fallback"),
                "articles":  r.get("article_count", 0),
                "headlines": r.get("headlines", []),
                "category":  r.get("dominant_category"),
                "ciLow":     r.get("ci_low"),
                "ciHigh":    r.get("ci_high"),
                "criteria":  [r.get("C1_severity"), r.get("C2_reach"),
                              r.get("C3_recoverability"), r.get("C4_criticality")],
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
