"""
nlp/finbert_pipeline.py
=======================
FinBERT sentiment analysis pipeline.

Downloads ProsusAI/finbert on first run (~500 MB).
Classifies text as positive / negative / neutral and
returns a sentiment score in [-1.0, +1.0].

Negative scores indicate financial/reputational risk.
Includes an intelligent heuristic mock fallback for offline or quick testing.
"""

import logging
import re
from typing import Union, List, Dict

try:
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch.nn.functional as F
    HAS_TORCH_TRANSFORMERS = True
except ImportError:
    HAS_TORCH_TRANSFORMERS = False

from config import FINBERT_MODEL, MODELS_DIR

logger = logging.getLogger(__name__)


class FinBERTPipeline:
    """
    Wrapper around ProsusAI/finbert for financial sentiment scoring.

    Label mapping (from the model card):
        0 → positive  → score  +p
        1 → negative  → score  -p
        2 → neutral   → score   0
    """

    _CACHE_DIR = str(MODELS_DIR / "finbert_cache")

    def __init__(self, device: str = "auto", use_mock: bool = False):
        self.use_mock = use_mock or not HAS_TORCH_TRANSFORMERS

        if self.use_mock:
            logger.info("Initializing FinBERT in Fallback/Heuristic mode.")
            self.device = "cpu"
            self.id2label = {0: "positive", 1: "negative", 2: "neutral"}
            return

        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info("Loading FinBERT model from %s …", FINBERT_MODEL)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                FINBERT_MODEL, cache_dir=self._CACHE_DIR
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                FINBERT_MODEL, cache_dir=self._CACHE_DIR
            ).to(self.device)
            self.model.eval()
            self.id2label = {0: "positive", 1: "negative", 2: "neutral"}
            logger.info("FinBERT loaded on device: %s", self.device)
        except Exception as exc:
            logger.warning(
                "Could not load HuggingFace model (%s). Falling back to heuristic sentiment scorer.",
                exc
            )
            self.use_mock = True

    def _heuristic_score(self, text: str) -> dict:
        """Heuristic lexicon-based scorer used when offline or in test mode."""
        negative_keywords = [
            "crisis", "protest", "delay", "scrutiny", "probe", "investigation",
            "violation", "fine", "fraud", "penalty", "default", "loss", "plunge",
            "drop", "fail", "controversy", "outage", "warn", "threat", "sebi",
            "rbi", "usfda", "risk", "unsecured", "debt", "slash", "complaint"
        ]
        positive_keywords = [
            "profit", "growth", "surge", "gain", "deal", "approval", "win",
            "record", "expansion", "partnership", "soar", "success", "dividend",
            "upgrade", "bullish", "strong", "recovery", "positive", "milestone"
        ]

        text_lower = text.lower()
        neg_count = sum(len(re.findall(r"\b" + re.escape(w) + r"\b", text_lower)) for w in negative_keywords)
        pos_count = sum(len(re.findall(r"\b" + re.escape(w) + r"\b", text_lower)) for w in positive_keywords)

        total = neg_count + pos_count
        if total == 0:
            return {"label": "neutral", "score": 0.0, "positive": 0.1, "negative": 0.1, "neutral": 0.8}

        neg_prob = round(min(0.95, 0.2 + 0.25 * neg_count), 4)
        pos_prob = round(min(0.95, 0.2 + 0.25 * pos_count), 4)
        neu_prob = round(max(0.05, 1.0 - (neg_prob + pos_prob) / 2), 4)

        if neg_count > pos_count:
            label = "negative"
            score = round(-neg_prob, 4)
        elif pos_count > neg_count:
            label = "positive"
            score = round(pos_prob, 4)
        else:
            label = "neutral"
            score = 0.0

        return {
            "label": label,
            "score": score,
            "positive": pos_prob,
            "negative": neg_prob,
            "neutral": neu_prob
        }

    def score_text(self, text: str) -> dict:
        """
        Score a single text string.
        """
        if not text or not text.strip():
            return {"label": "neutral", "score": 0.0,
                    "positive": 0.0, "negative": 0.0, "neutral": 1.0}

        if self.use_mock:
            return self._heuristic_score(text)

        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        ).to(self.device)

        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs = F.softmax(logits, dim=-1)[0]

        p_pos = probs[0].item()
        p_neg = probs[1].item()
        p_neu = probs[2].item()
        signed_score = round(p_pos - p_neg, 4)
        dominant_idx = int(probs.argmax())
        label = self.id2label[dominant_idx]

        return {
            "label": label,
            "score": signed_score,
            "positive": round(p_pos, 4),
            "negative": round(p_neg, 4),
            "neutral": round(p_neu, 4),
        }

    def score_batch(self, texts: List[str], batch_size: int = 16) -> List[dict]:
        """
        Score a list of texts.
        """
        if not texts:
            return []

        if self.use_mock:
            return [self._heuristic_score(t) for t in texts]

        results = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            inputs = self.tokenizer(
                batch,
                return_tensors="pt",
                truncation=True,
                max_length=512,
                padding=True,
            ).to(self.device)

            with torch.no_grad():
                logits = self.model(**inputs).logits
            probs = F.softmax(logits, dim=-1)

            for row in probs:
                p_pos = row[0].item()
                p_neg = row[1].item()
                p_neu = row[2].item()
                signed = round(p_pos - p_neg, 4)
                dom = int(row.argmax())
                results.append({
                    "label": self.id2label[dom],
                    "score": signed,
                    "positive": round(p_pos, 4),
                    "negative": round(p_neg, 4),
                    "neutral": round(p_neu, 4),
                })
        return results

    def aggregate_scores(self, scores: List[dict]) -> dict:
        """
        Aggregate a list of per-headline score dicts.
        """
        if not scores:
            return {"compound_score": 0.0, "negative_ratio": 0.0, "article_count": 0}

        signed_scores = [s["score"] for s in scores]
        neg_count = sum(1 for s in scores if s["label"] == "negative")

        return {
            "compound_score": round(sum(signed_scores) / len(signed_scores), 4),
            "negative_ratio": round(neg_count / len(scores), 4),
            "article_count": len(scores),
        }


# ── Convenience singleton ────────────────────────────────────────────────────

_pipeline_instance: Union[FinBERTPipeline, None] = None


def get_pipeline(device: str = "auto", use_mock: bool = False) -> FinBERTPipeline:
    """Return a cached FinBERTPipeline."""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = FinBERTPipeline(device=device, use_mock=use_mock)
    return _pipeline_instance
