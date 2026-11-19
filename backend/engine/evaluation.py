"""
engine/evaluation.py
====================
Sentiment accuracy check against human labels (report Sec. VII-C:
"hand-label a sample of headlines and report FinBERT accuracy").

Headlines from the latest run are shown to a reviewer in the Validation tab,
who labels each as negative / neutral / positive WITHOUT seeing the model's
prediction. Labels are stored in backend/data/labels.json. Metrics compare
every available sentiment engine (the finance word list always, FinBERT when
installed) against those labels: accuracy, macro-F1, per-class precision /
recall / F1 and the confusion matrix. The crisis category of each labelled
headline is listed too, so the classifier can be checked by eye.

The sample is stratified by the model's predicted label (equal numbers of
predicted negative / neutral / positive where available) so rarer classes get
enough examples. Accuracy on a stratified sample is not the same as accuracy
on the natural mix of news; the dashboard says so.
"""

import json
import random
import threading
from datetime import datetime, timezone

from config import LABELS_FILE
from nlp.crisis_classifier import classify

CLASSES = ["negative", "neutral", "positive"]
_lock = threading.Lock()


def load_labels() -> list:
    if LABELS_FILE.exists():
        return json.loads(LABELS_FILE.read_text(encoding="utf-8")).get("labels", [])
    return []


def _save(labels):
    LABELS_FILE.write_text(json.dumps({"labels": labels}, indent=1, ensure_ascii=False), encoding="utf-8")


def add_label(title: str, label: str, company: str = "") -> int:
    if label not in CLASSES + ["skip"]:
        raise ValueError("label must be negative, neutral, positive or skip")
    with _lock:
        labels = [x for x in load_labels() if x["title"] != title]
        labels.append({"title": title, "label": label, "company": company,
                       "labelled_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")})
        _save(labels)
        return sum(1 for x in labels if x["label"] != "skip")


def clear_labels() -> None:
    with _lock:
        _save([])


def sample(pool: list, n: int = 15, seed: int | None = None) -> list:
    """Stratified sample of unlabelled headlines. pool items: title, label, company, outlet."""
    done = {x["title"] for x in load_labels()}
    seen, items = set(), []
    for a in pool:
        t = (a.get("title") or "").strip()
        if t and t not in done and t not in seen:
            seen.add(t)
            items.append(a)
    rng = random.Random(seed)
    by_pred = {c: [a for a in items if a.get("label") == c] for c in CLASSES}
    for v in by_pred.values():
        rng.shuffle(v)
    out, k = [], 0
    while len(out) < n and any(by_pred.values()):
        c = CLASSES[k % 3]
        if by_pred[c]:
            out.append(by_pred[c].pop())
        k += 1
    rng.shuffle(out)
    return [{"title": a["title"], "company": a.get("company", ""), "outlet": a.get("outlet", "")} for a in out]


def report(gold: list[str], pred: list[str]) -> dict:
    cm = {g: {p: 0 for p in CLASSES} for g in CLASSES}
    for g, p in zip(gold, pred):
        cm[g][p] += 1
    per = {}
    for c in CLASSES:
        tp = cm[c][c]
        fp = sum(cm[g][c] for g in CLASSES if g != c)
        fn = sum(cm[c][p] for p in CLASSES if p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        per[c] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3), "support": tp + fn}
    n = len(gold)
    acc = sum(g == p for g, p in zip(gold, pred)) / n if n else 0.0
    present = [c for c in CLASSES if per[c]["support"]]
    macro = sum(per[c]["f1"] for c in present) / len(present) if present else 0.0
    return {"accuracy": round(acc, 3), "macroF1": round(macro, 3), "perClass": per, "confusion": cm}


def metrics(engines: dict) -> dict:
    """engines: {"lexicon": SentimentEngine, "finbert": SentimentEngine (optional)}."""
    labelled = [x for x in load_labels() if x["label"] in CLASSES]
    out = {"labelled": len(labelled), "skipped": sum(1 for x in load_labels() if x["label"] == "skip")}
    if not labelled:
        return out
    titles = [x["title"] for x in labelled]
    gold = [x["label"] for x in labelled]
    preds = {name: [s["label"] for s in eng.score_batch(titles)] for name, eng in engines.items()}
    out.update({
        "engines": {name: report(gold, p) for name, p in preds.items()},
        "majorityBaseline": round(max(gold.count(c) for c in CLASSES) / len(gold), 3),
        "goldDistribution": {c: gold.count(c) for c in CLASSES},
        "disagreements": [{"title": t, "gold": g, **{name: p[i] for name, p in preds.items()},
                           "category": classify(t)["category"]}
                          for i, (t, g) in enumerate(zip(titles, gold))
                          if any(p[i] != g for p in preds.values())][:40],
    })
    return out
