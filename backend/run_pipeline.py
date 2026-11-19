"""
run_pipeline.py
===============
Command-line runner for the NSE Brand Risk pipeline.

  py -3 backend/run_pipeline.py                     # full run: download prices + news, score, update dashboard
  py -3 backend/run_pipeline.py --offline           # re-score using the last downloaded data (no network)
  py -3 backend/run_pipeline.py --limit 5           # quick test on the first 5 companies (not saved)
  py -3 backend/run_pipeline.py --sentiment finbert # force FinBERT (needs requirements-finbert.txt)
  py -3 backend/run_pipeline.py --eval-ahp          # print the AHP matrix, weights and consistency
  py -3 backend/run_pipeline.py --test-headline "SEBI probes accounting lapses at XYZ"
  py -3 backend/run_pipeline.py --backtest          # re-run the 12-incident back-test (~3 min)
  py -3 backend/run_pipeline.py --search Swiggy     # score any NSE company now
  py -3 backend/run_pipeline.py --search Paytm --as-of 2024-02-04   # … or as of a past day
"""

import argparse
import json
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Windows consoles default to cp1252; make output UTF-8 so symbols like λ print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("pipeline")


def eval_ahp():
    from engine.criteria import CRITERIA
    from mcdm.ahp import AHP
    res = AHP().compute()
    names = [c["name"] for c in CRITERIA]
    print("\nAHP pairwise comparison matrix")
    print(" " * 20 + "".join(f"{k:>8}" for k in res["keys"]))
    for name, key, row in zip(names, res["keys"], res["matrix"]):
        print(f"{key} {name:<17}" + "".join(f"{v:>8.3f}" for v in row))
    print("\nPriority weights (principal eigenvector)")
    for name, key, w in zip(names, res["keys"], res["weights"]):
        print(f"  {key} {name:<18} {w:.4f}  {'█' * round(w * 60)}")
    print(f"\n  λmax = {res['lambda_max']:.4f}   CI = {res['CI']:.4f}   RI = {res['RI']}   "
          f"CR = {res['CR']:.4f}  → {'consistent (< 0.10)' if res['consistent'] else 'INCONSISTENT'}\n")


def test_headline(text: str, engine: str):
    from nlp.crisis_classifier import classify, regulators_mentioned
    from nlp.sentiment import SentimentEngine
    eng = SentimentEngine(engine)
    s = eng.score_batch([text])[0]
    c = classify(text)
    regs = regulators_mentioned(text)
    print(f"\nEngine : {eng.name}\nText   : {text}\nScore  : {s['score']:+.3f}  → {s['label'].upper()}")
    print(f"Issue  : {c['category']}" + (f" (matched '{c['keyword']}')" if c["keyword"] else ""))
    if regs:
        print(f"Regulators: {', '.join(regs)}")
    print()


def run_backtest(engine: str):
    from config import LATEST_FILE
    from engine.backtest import run_backtest as _run
    from engine.risk_scorer import write_frontend_data
    from nlp.sentiment import SentimentEngine
    res = _run(SentimentEngine(engine))
    if res.get("status") != "done":
        print("Back-test failed:", res.get("error"))
        return
    m = res["metrics"]
    print(f"\nBack-test on {m['incidents']} incidents (sentiment: {res['sentimentEngine']}); flag = score ≥ {m['flagThreshold']}")
    print(f"{'Method':<16}{'pairwise acc.':>14}{'hit rate':>10}{'false alarm':>13}{'mean incident':>15}{'mean control':>14}")
    for k, label in [("index", "Risk index"), ("stockOnly", "Stock only"), ("newsOnly", "News only"),
                     ("sentimentOnly", "Sentiment only"), ("mentionVolume", "Mention volume")]:
        hr, fa = m["hitRate"].get(k), m["falseAlarmRate"].get(k)
        print(f"{label:<16}{m['pairwiseAccuracy'][k]:>14.2f}{'' if hr is None else f'{hr:.2f}':>10}"
              f"{'' if fa is None else f'{fa:.2f}':>13}{m['mean'][k]['incident']:>15}{m['mean'][k]['control']:>14}")
    for r in res["rows"]:
        print(f"  {r['company']:<22} {r['date']}  incident {r['incident']['index']:5.1f}  control {r['control']['index']:5.1f}"
              f"  {'detected' if r['detected'] else '-':<9} {r['event'][:60]}")
    if LATEST_FILE.exists():           # show the new results on the dashboard
        payload = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
        payload["backtest"] = {k: v for k, v in res.items() if k != "status"}
        LATEST_FILE.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        write_frontend_data(payload)


def run_search(query: str, as_of: str | None, engine: str):
    from datetime import date
    from engine.search import search_company
    from nlp.sentiment import SentimentEngine
    res = search_company(query, SentimentEngine(engine), date.fromisoformat(as_of) if as_of else None)
    c = res["company"]
    rng = f", 90% range {c['range'][0]}–{c['range'][1]}" if c.get("range") else ""
    print(f"\n{c['name']} (NSE: {c['symbol']}, {c['sector']}) as of {c['asOf']}: score {c['score']} ({c['level']}){rng}")
    for k, v in zip(["Market reaction", "Trading stress", "Lingering damage", "News tone", "Negative coverage"], c["criteria"]):
        print(f"  {k:<18} {v:5.1f}")
    print(f"  Main issue: {c['issue']['dominant']} · headlines {c['news']['count7d']} (negative {c['news']['neg7d']})\n")


def main():
    ap = argparse.ArgumentParser(description="NSE Brand Risk pipeline")
    ap.add_argument("--offline", action="store_true", help="use cached downloads, no network")
    ap.add_argument("--sentiment", choices=["auto", "finbert", "lexicon"], default="auto")
    ap.add_argument("--limit", type=int, help="only score the first N watchlist companies (test run, nothing saved)")
    ap.add_argument("--no-export", action="store_true", help="do not overwrite js/data.js")
    ap.add_argument("--reset-history", action="store_true", help="discard stored history and backfill again")
    ap.add_argument("--no-feeds", action="store_true", help="Google News only (skip the direct outlet feeds)")
    ap.add_argument("--eval-ahp", action="store_true")
    ap.add_argument("--test-headline", type=str)
    ap.add_argument("--backtest", action="store_true", help="re-run the incident back-test (~3 min)")
    ap.add_argument("--search", type=str, help="score any NSE company now (name or symbol)")
    ap.add_argument("--as-of", type=str, help="with --search: score as of a past day, YYYY-MM-DD")
    args = ap.parse_args()

    if args.eval_ahp:
        return eval_ahp()
    if args.test_headline:
        return test_headline(args.test_headline, args.sentiment)
    if args.backtest:
        return run_backtest(args.sentiment)
    if args.search:
        return run_search(args.search, args.as_of, args.sentiment)

    from engine.risk_scorer import BrandRiskPipeline
    pipe = BrandRiskPipeline(offline=args.offline, sentiment=args.sentiment, limit=args.limit,
                             reset_history=args.reset_history, feeds=not args.no_feeds)
    payload = pipe.run()

    if args.limit:
        logger.info("Test run (--limit) — results not saved")
    else:
        pipe.save(export_frontend=not args.no_export)

    rows = payload["companies"]
    print(f"\nNSE Brand Risk · {payload['universe']} · as of {payload['asOf']} · sentiment: {payload['sentimentEngine']}")
    print(f"{'#':>3} {'Symbol':<12}{'Company':<22}{'Score':>6}  {'Level':<9}{'C1':>6}{'C2':>6}{'C3':>6}{'C4':>6}{'C5':>6}  {'Specific 5d':>11}  News(neg)")
    for r in rows:
        c = r["criteria"]
        ex = r["stock"]["excess5"]
        print(f"{r['rank']:>3} {r['symbol']:<12}{r['name'][:21]:<22}{r['score']:>6.1f}  {r['level']:<9}"
              f"{c[0]:>6.1f}{c[1]:>6.1f}{c[2]:>6.1f}{c[3]:>6.1f}{c[4]:>6.1f}  {ex * 100:>+10.1f}%  "
              f"{r['news']['count7d']:>3} ({r['news']['neg7d']})")
    if payload["skipped"]:
        print("\nSkipped:", ", ".join(f"{s['symbol']} ({s['reason']})" for s in payload["skipped"]))


if __name__ == "__main__":
    main()
