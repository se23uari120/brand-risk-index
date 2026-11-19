"""
engine/evaluation.py
====================
FinBERT accuracy check against human labels (report Sec. VII-C:
"hand-label a sample of headlines and report FinBERT accuracy").

Headlines from the latest live run are shown to a reviewer, who labels each
as negative / neutral / positive WITHOUT seeing the model's prediction.
Labels are stored in backend/data/labels.json. Metrics compare FinBERT and
the keyword heuristic against those labels: accuracy, macro-F1, per-class
precision / recall / F1 and the confusion matrix. Crisis categories are
also reported per labelled headline so the classifier can be checked by eye.

The sample is stratified by FinBERT's predicted label (equal numbers of
predicted negative / neutral / positive where available), so rarer classes
get enough examples. Accuracy on a stratified sample is not the same as
accuracy on the natural mix of news; the dashboard says so.
"""

import json
import random
import threading
from datetime import datetime, timezone

from config import DATA_DIR
from nlp.crisis_classifier import classify

LABELS_PATH = DATA_DIR / "labels.json"
CLASSES = ["negative", "neutral", "positive"]
_lock = threading.Lock()


def load_labels() -> list:
    if LABELS_PATH.exists():
        with open(LABELS_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("labels", [])
    return []


def _save(labels):
    with open(LABELS_PATH, "w", encoding="utf-8") as f:
        json.dump({"labels": labels}, f, indent=1, ensure_ascii=False)


def add_label(title: str, label: str, company: str = "", reviewer: str = "") -> int:
    if label not in CLASSES + ["skip"]:
        raise ValueError("label must be negative, neutral, positive or skip")
    with _lock:
        labels = [x for x in load_labels() if x["title"] != title]
        labels.append({"title": title, "label": label, "company": company, "reviewer": reviewer,
                       "labelled_at": datetime.now(tz=timezone.utc).isoformat()})
        _save(labels)
        return sum(1 for x in labels if x["label"] != "skip")


def clear_labels() -> None:
    with _lock:
        _save([])


def sample(pool: list, n: int = 15, seed: int | None = None) -> list:
    """Stratified sample of unlabelled headlines. pool items need title/label."""
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


def _report(gold, pred):
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
        per[c] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(f1, 3),
                  "support": tp + fn}
    n = len(gold)
    acc = sum(g == p for g, p in zip(gold, pred)) / n if n else 0.0
    present = [c for c in CLASSES if per[c]["support"]]
    macro = sum(per[c]["f1"] for c in present) / len(present) if present else 0.0
    return {"accuracy": round(acc, 3), "macro_f1": round(macro, 3), "per_class": per,
            "confusion": cm}


def metrics(bert, heuristic) -> dict:
    labelled = [x for x in load_labels() if x["label"] in CLASSES]
    if not labelled:
        return {"labelled": 0}
    titles = [x["title"] for x in labelled]
    gold = [x["label"] for x in labelled]
    fin = bert.score_batch(titles)
    heu = heuristic.score_batch(titles)
    rows = [{"title": t, "gold": g, "finbert": f["label"], "finbert_score": f["score"],
             "heuristic": h["label"], "category": classify(t)["category"]}
            for t, g, f, h in zip(titles, gold, fin, heu)]
    return {
        "labelled": len(labelled),
        "skipped": sum(1 for x in load_labels() if x["label"] == "skip"),
        "finbert_is_model": not bert.use_mock,
        "finbert": _report(gold, [r["finbert"] for r in rows]),
        "heuristic": _report(gold, [r["heuristic"] for r in rows]),
        "majority_baseline": round(max(gold.count(c) for c in CLASSES) / len(gold), 3),
        "gold_distribution": {c: gold.count(c) for c in CLASSES},
        "disagreements": [r for r in rows if r["gold"] != r["finbert"]][:50],
    }
