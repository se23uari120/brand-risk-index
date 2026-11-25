"""
nlp/sentiment.py
================
Scores each headline from −1 (very negative) to +1 (very positive).

Two engines, same output format:

* FinBERT  (ProsusAI/finbert) — a BERT model fine-tuned on financial news.
  Used automatically when `torch` and `transformers` are installed
  (pip install -r backend/requirements-finbert.txt). ~440 MB download once.
      score = P(positive) − P(negative)

* Lexicon — a transparent, dependency-free fallback built from finance /
  reputation vocabulary ("probe", "penalty", "recall", "downgrade" … vs
  "order win", "upgrade", "record profit" …). Each term has a weight 1–3.
      score = (P − N) / (P + N + 1.5)       P, N = summed term weights

A headline is labelled negative if score ≤ −0.15, positive if ≥ +0.15.

CachedSentiment wraps an engine with stored scores: the daily FinBERT run
saves every headline's score (output/sentiment_cache.json), and a small server
that cannot load FinBERT reuses those scores and uses its own engine (the word
list) only for headlines published since.
"""

import json
import logging
import re
import threading

from config import (FINBERT_MODEL, MODELS_DIR, SENTIMENT_CACHE_FILE, SENTIMENT_NEG_THRESHOLD,
                    SENTIMENT_POS_THRESHOLD)

logger = logging.getLogger(__name__)


def label_for(score: float) -> str:
    if score <= SENTIMENT_NEG_THRESHOLD:
        return "negative"
    if score >= SENTIMENT_POS_THRESHOLD:
        return "positive"
    return "neutral"


# ── Lexicon engine ───────────────────────────────────────────────────────────

NEGATIVE_TERMS = {
    # legal / regulatory / governance
    "fraud": 3, "scam": 3, "money laundering": 3, "insider trading": 3, "warning letter": 3,
    "insolvency": 3, "bankruptcy": 3, "default": 2, "defaults": 2,
    "probe": 2, "probes": 2, "investigation": 2, "raid": 2, "raids": 2, "searches": 1,
    "penalty": 2, "penalised": 2, "penalized": 2, "fined": 2, "fine of": 2,
    "lawsuit": 2, "sued": 2, "sues": 2, "litigation": 2, "show-cause": 2, "show cause": 2,
    "violation": 2, "violations": 2, "non-compliance": 2, "allegation": 2, "allegations": 2,
    "alleged": 1, "accused": 2, "whistleblower": 2, "audit qualification": 2,
    "sebi order": 2, "sebi bars": 3, "rbi action": 2, "rbi bars": 3, "ban": 2, "banned": 2,
    "form 483": 2, "import alert": 3, "observations": 1, "notice": 1, "tax demand": 2,
    # operations / brand
    "recall": 2, "recalls": 2, "outage": 2, "on strike": 2, "nationwide strike": 2,
    "workers' strike": 2, "workers strike": 2, "strike call": 2, "strike notice": 2, "protest": 2, "protests": 2,
    "boycott": 2, "backlash": 2, "controversy": 2, "complaints": 1, "complaint": 1,
    "layoff": 2, "layoffs": 2, "job cuts": 2, "resigns": 1, "resignation": 1, "quits": 1,
    "accident": 2, "fire": 1, "blast": 2, "explosion": 2, "death": 2, "deaths": 2, "killed": 2,
    "shutdown": 2, "halts": 1, "suspends": 1, "suspended": 1, "delay": 1, "delays": 1,
    "crisis": 2, "data breach": 3, "cyberattack": 3, "hacked": 2, "glitch": 1,
    # financial results / market
    "loss": 2, "losses": 2, "net loss": 2, "profit falls": 2, "profit drops": 2,
    "misses": 1, "weak": 1, "subdued": 1, "disappoint": 2, "disappoints": 2, "slowdown": 1,
    "downgrade": 2, "downgrades": 2, "downgraded": 2, "sell rating": 2, "underperform": 1,
    "target cut": 2, "cuts target": 2, "lowers target": 2, "write-off": 2, "impairment": 2,
    "plunge": 2, "plunges": 2, "plummets": 2, "crash": 2, "crashes": 2, "tanks": 2,
    "slump": 2, "slumps": 2, "tumble": 2, "tumbles": 2, "sinks": 2, "slides": 1, "slips": 1,
    "falls": 1, "fall": 1, "drops": 1, "declines": 1, "decline": 1, "dips": 1, "down": 1,
    "sell-off": 2, "selloff": 2, "52-week low": 2, "lower circuit": 2, "concern": 1,
    "concerns": 1, "worries": 1, "risk": 1, "pressure": 1, "headwinds": 1, "scrutiny": 1,
    "warns": 1, "warning": 1, "pledge": 1,
}

POSITIVE_TERMS = {
    "record profit": 3, "record high": 2, "all-time high": 2, "52-week high": 2,
    "upper circuit": 2, "beats estimates": 2, "beats": 2, "upgrade": 2, "upgrades": 2,
    "upgraded": 2, "buy rating": 2, "outperform": 1, "raises target": 2, "target raised": 2,
    "order win": 2, "wins order": 2, "bags order": 2, "bags": 1, "wins": 1,
    "surge": 2, "surges": 2, "soars": 2, "jumps": 2, "rallies": 2, "zooms": 2,
    "rises": 1, "gains": 1, "climbs": 1, "higher": 1,
    "profit rises": 2, "profit jumps": 2, "strong": 1, "robust": 1, "growth": 1,
    "expansion": 1, "expands": 1, "partnership": 1, "partners": 1, "acquires": 1,
    "approval": 1, "approves": 1, "nod": 1, "dividend": 1, "bonus": 1, "buyback": 1,
    "milestone": 1, "launches": 1, "bullish": 1, "recovery": 1, "rebounds": 1,
}

_NEGATORS = re.compile(r"\b(no|not|without|denies|deny|rules out)\s+(\w+\s+)?$", re.IGNORECASE)


def _compile(terms: dict) -> list[tuple[re.Pattern, int]]:
    # longest phrases first so "record profit" wins over "profit"
    ordered = sorted(terms.items(), key=lambda kv: -len(kv[0]))
    return [(re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"), w) for t, w in ordered]


_NEG = _compile(NEGATIVE_TERMS)
_POS = _compile(POSITIVE_TERMS)


def lexicon_score(text: str) -> dict:
    t = text.lower()
    totals = {"neg": 0.0, "pos": 0.0}
    for bucket, patterns in (("neg", _NEG), ("pos", _POS)):
        for pat, w in patterns:
            for mt in list(pat.finditer(t)):
                if _NEGATORS.search(t[:mt.start()]):       # "no fraud found" → ignore
                    continue
                totals[bucket] += w
            t = pat.sub(" ", t)                            # don't double count sub-phrases
    neg, pos = totals["neg"], totals["pos"]
    score = round((pos - neg) / (pos + neg + 1.5), 4)
    return {"score": score, "label": label_for(score),
            "positive": round(max(score, 0), 4), "negative": round(max(-score, 0), 4),
            "neutral": round(1 - abs(score), 4)}


# ── Engine wrapper ───────────────────────────────────────────────────────────

class SentimentEngine:
    """engine = 'auto' | 'finbert' | 'lexicon'"""

    def __init__(self, engine: str = "auto"):
        self.name = "lexicon"
        if engine in ("auto", "finbert"):
            try:
                import torch  # noqa: F401
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                cache = str(MODELS_DIR / "finbert_cache")
                self._torch = torch
                self.tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL, cache_dir=cache)
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    FINBERT_MODEL, cache_dir=cache).eval()
                labels = {v.lower(): k for k, v in self.model.config.id2label.items()}
                self._idx = (labels["positive"], labels["negative"], labels["neutral"])
                self.name = "finbert"
                logger.info("Sentiment engine: FinBERT (%s)", FINBERT_MODEL)
            except Exception as exc:
                if engine == "finbert":
                    raise RuntimeError(f"FinBERT requested but unavailable: {exc}") from exc
                logger.info("FinBERT unavailable (%s) — using lexicon engine", type(exc).__name__)
        if self.name == "lexicon":
            logger.info("Sentiment engine: lexicon")

    def score_batch(self, texts: list[str], batch_size: int = 32) -> list[dict]:
        if self.name == "lexicon":
            return [lexicon_score(t) for t in texts]
        out = []
        torch = self._torch
        ip, ineg, ineu = self._idx
        for i in range(0, len(texts), batch_size):
            enc = self.tokenizer(texts[i:i + batch_size], return_tensors="pt",
                                 truncation=True, max_length=128, padding=True)
            with torch.no_grad():
                probs = torch.softmax(self.model(**enc).logits, dim=-1)
            for row in probs:
                p_pos, p_neg, p_neu = row[ip].item(), row[ineg].item(), row[ineu].item()
                s = round(p_pos - p_neg, 4)
                out.append({"score": s, "label": label_for(s), "positive": round(p_pos, 4),
                            "negative": round(p_neg, 4), "neutral": round(p_neu, 4)})
        return out


# ── stored scores: the daily FinBERT run → small servers ─────────────────────
def load_score_cache(path=SENTIMENT_CACHE_FILE) -> dict:
    """{headline: score} saved by the last FinBERT run, or {} if there is none."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.get("scores", {}).items()}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Ignoring unreadable sentiment cache %s: %s", path, exc)
        return {}


def save_score_cache(scores: dict, engine: str, path=SENTIMENT_CACHE_FILE) -> None:
    """One headline per line (sorted), so the daily commit's diff stays small."""
    body = {"engine": engine, "scores": {k: round(float(v), 4) for k, v in sorted(scores.items())}}
    path.write_text(json.dumps(body, indent=0, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved %d %s headline scores to %s", len(scores), engine, path.name)


class CachedSentiment:
    """
    Answers from stored scores first (FinBERT's, from the daily run) and asks
    the wrapped engine only for headlines it has not seen. `name` stays the
    wrapped engine's; `label()` says what was actually used, e.g.
    'finbert+lexicon', and `mix()` how many headlines came from each.
    """

    def __init__(self, engine, stored: dict, stored_name: str = "finbert"):
        self.engine, self.stored, self.stored_name = engine, stored, stored_name
        self.name = engine.name
        self.hits = self.misses = 0
        self._lock = threading.Lock()

    def score_batch(self, texts: list[str], batch_size: int = 32) -> list[dict]:
        out: list = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            s = self.stored.get(t)
            if s is None:
                todo.append(i)
            else:
                out[i] = {"score": s, "label": label_for(s)}
        if todo:
            for i, r in zip(todo, self.engine.score_batch([texts[i] for i in todo], batch_size)):
                out[i] = r
        with self._lock:
            self.hits += len(texts) - len(todo)
            self.misses += len(todo)
        return out

    def label(self) -> str:
        if self.engine.name == self.stored_name or not self.hits:
            return self.engine.name
        return f"{self.stored_name}+{self.engine.name}" if self.misses else self.stored_name

    def mix(self) -> dict:
        return {self.stored_name: self.hits, self.engine.name: self.misses}
