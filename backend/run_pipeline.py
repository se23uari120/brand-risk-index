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
"""

import argparse
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
    from nlp.sentiment import SentimentEngine
    eng = SentimentEngine(engine)
    s = eng.score_batch([text])[0]
    print(f"\nEngine : {eng.name}\nText   : {text}\nScore  : {s['score']:+.3f}  → {s['label'].upper()}\n")


def main():
    ap = argparse.ArgumentParser(description="NSE Brand Risk pipeline")
    ap.add_argument("--offline", action="store_true", help="use cached downloads, no network")
    ap.add_argument("--sentiment", choices=["auto", "finbert", "lexicon"], default="auto")
    ap.add_argument("--limit", type=int, help="only score the first N watchlist companies (test run, nothing saved)")
    ap.add_argument("--no-export", action="store_true", help="do not overwrite js/data.js")
    ap.add_argument("--reset-history", action="store_true", help="discard stored history and backfill again")
    ap.add_argument("--eval-ahp", action="store_true")
    ap.add_argument("--test-headline", type=str)
    args = ap.parse_args()

    if args.eval_ahp:
        return eval_ahp()
    if args.test_headline:
        return test_headline(args.test_headline, args.sentiment)

    from engine.risk_scorer import BrandRiskPipeline
    pipe = BrandRiskPipeline(offline=args.offline, sentiment=args.sentiment,
                             limit=args.limit, reset_history=args.reset_history)
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
