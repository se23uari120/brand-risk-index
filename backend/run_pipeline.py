"""
run_pipeline.py
===============
Command-line interface to execute the FinBERT NLP + AHP-TOPSIS MCDM pipeline.

Usage:
  python run_pipeline.py                     # Run live pipeline with FinBERT
  python run_pipeline.py --mode mock         # Fast run using heuristic FinBERT (no 500MB download)
  python run_pipeline.py --offline           # Run offline using cached feeds
  python run_pipeline.py --sync-frontend     # Write output directly to js/data.js
  python run_pipeline.py --eval-ahp          # Display AHP matrix, weights & CR
  python run_pipeline.py --test-bert "RBI imposes penalty on digital lending"
"""

import argparse
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path so imports work cleanly from anywhere
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from mcdm.ahp import get_default_ahp, DEFAULT_PAIRWISE, CRITERIA_NAMES
from nlp.finbert_pipeline import get_pipeline
from engine.risk_scorer import RiskScoringPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_pipeline")


def print_banner():
    print("""
=============================================================
   AI + MCDM BRAND IMAGE RISK INDEX PIPELINE
   FinBERT Sentiment NLP + AHP-TOPSIS Multi-Criteria Engine
=============================================================
""")


def display_ahp():
    print("\n--- AHP Pairwise Comparison Matrix (4x4) ---")
    headers = ["Criterion"] + CRITERIA_NAMES
    print(f"{headers[0]:<20} " + " ".join(f"{h:>18}" for h in headers[1:]))
    print("-" * 95)
    for i, name in enumerate(CRITERIA_NAMES):
        row_vals = " ".join(f"{DEFAULT_PAIRWISE[i, j]:>18.3f}" for j in range(4))
        print(f"{name:<20} {row_vals}")

    ahp = get_default_ahp()
    res = ahp.compute()
    print("\n--- AHP Weight Derivation & Consistency Check ---")
    for crit, w in res["weights"].items():
        print(f"  {crit:<20}: {w:.4f} ({w*100:.1f}%)")
    print(f"\n  lambda_max         : {res['lambda_max']:.4f}")
    print(f"  Consistency Index  : {res['CI']:.4f}")
    print(f"  Consistency Ratio  : {res['CR']:.4f} (Threshold < 0.10 -> {'PASSED' if res['CR_acceptable'] else 'FAILED'})")
    print("=" * 60)


def test_bert_headline(text: str, use_mock: bool):
    print(f"\nAnalyzing Sentiment for:\n\"{text}\"\n")
    bert = get_pipeline(use_mock=use_mock)
    res = bert.score_text(text)
    print(f"Classification : {res['label'].upper()}")
    print(f"Signed Score   : {res['score']:+.4f}  [-1.0 (Critical Risk) to +1.0 (Positive)]")
    print(f"Probabilities  : Neg={res['negative']:.3f} | Neu={res['neutral']:.3f} | Pos={res['positive']:.3f}")
    print("=" * 60)


def run_full_pipeline(args):
    use_mock = (args.mode == "mock")
    pipeline = RiskScoringPipeline(
        lookback_hours=args.lookback,
        use_mock=use_mock,
        offline=args.offline
    )

    logger.info("Executing pipeline (mode=%s, offline=%s)...", args.mode, args.offline)
    results = pipeline.run(verbose=True)

    # Persist results
    json_path = pipeline.save_results(results)
    print(f"\n[+] Results JSON saved to: {json_path}")

    # Sync to frontend
    if args.sync_frontend:
        frontend_js = pipeline.export_to_frontend(results)
        print(f"[+] Synced to Frontend Dashboard: {frontend_js}")

    # Print summary table in console
    print("\n" + "=" * 105)
    print(f"{'ID':<8} {'Company':<22} {'Sector':<20} {'Risk':>6} {'Level':<10} {'Sentiment':>10} {'Reach':<8} {'Action Trigger'}")
    print("=" * 105)
    for c in results:
        print(f"{c['id']:<8} {c['name']:<22} {c['sector']:<20} {c['risk_index']:>6.1f} {c['level']:<10} {c['compound_sentiment']:>10.2f} {c['reach_label']:<8} {c['action']}")
    print("=" * 105 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Brand Image Risk Index Pipeline Runner")
    parser.add_argument("--mode", choices=["live", "mock"], default="mock",
                        help="Execution mode: 'live' (FinBERT transformer) or 'mock' (heuristic fallback)")
    parser.add_argument("--offline", action="store_true", default=False,
                        help="Do not scrape external RSS; use local queries & caches")
    parser.add_argument("--lookback", type=int, default=24,
                        help="Lookback window in hours for news feeds (default: 24)")
    parser.add_argument("--sync-frontend", action="store_true", default=True,
                        help="Sync results directly to js/data.js (default: True)")
    parser.add_argument("--eval-ahp", action="store_true",
                        help="Print AHP pairwise matrix, priority weights & consistency ratio")
    parser.add_argument("--test-bert", type=str, default="",
                        help="Test FinBERT sentiment scoring on a custom string")

    args = parser.parse_args()

    print_banner()

    if args.eval_ahp:
        display_ahp()
        return

    if args.test_bert:
        test_bert_headline(args.test_bert, use_mock=(args.mode == "mock"))
        return

    run_full_pipeline(args)


if __name__ == "__main__":
    main()
