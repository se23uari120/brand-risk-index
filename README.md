---
title: Brand Image Risk Index
emoji: 📊
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: FinBERT + AHP-TOPSIS reputational risk for any company
---

# AI + MCDM Brand Image Risk Index

A decision-support system that scores the reputational risk of companies from live news: headlines from Indian business outlets, Moneycontrol and Google News are scored with **FinBERT**, turned into four criteria, weighted with **AHP** and ranked with **TOPSIS** into a 0–100 Brand Image Risk Index with Low / Moderate / Critical bands and a prescribed action. Search any company, live or for a past date range.

* **Public live app (search + live news):** <!-- HF_LINK -->see "Deploy a public live link" below
* **Static demo (stored data only, no search):** https://se23uari120.github.io/brand-risk-index/
* **Repository:** https://github.com/se23uari120/brand-risk-index

(The block between `---` lines above is configuration for Hugging Face Spaces.)

---

## Quick start on any computer

Needs **Python 3.10+** and **Git**.

**Windows (Command Prompt):**
```bat
git clone https://github.com/se23uari120/brand-risk-index.git
cd brand-risk-index
setup.bat
start.bat
```

**macOS / Linux:**
```bash
git clone https://github.com/se23uari120/brand-risk-index.git
cd brand-risk-index
chmod +x setup.sh start.sh
./setup.sh
./start.sh
```

Then open **http://localhost:8000**. `setup` runs once; afterwards only `start` is needed. FinBERT (~440 MB) downloads on the first start.

**With Docker:** `docker build -t brand-risk-index .` then `docker run -p 7860:7860 brand-risk-index` → http://localhost:7860

---

## Deploy a public live link (Hugging Face Spaces, free)

GitHub Pages can only host the static dashboard, because live news, search and FinBERT need the Python server. Hugging Face Spaces runs the `Dockerfile` in this repo for free (2 CPU, 16 GB RAM):

1. Create a free account at https://huggingface.co and an access token with **write** permission (Settings → Access Tokens).
2. In this folder run `.venv\Scripts\hf auth login` (Windows) or `.venv/bin/hf auth login` and paste the token.
3. Create the Space and upload the code:
   ```bash
   hf repos create YOUR-NAME/brand-risk-index --type space --space-sdk docker --public
   hf upload YOUR-NAME/brand-risk-index . . --repo-type space --exclude ".venv/*" "backend/models/*" ".git/*" "**/__pycache__/*" "backend/output/risk_results_*"
   ```
4. The first build takes about 5–10 minutes. The app is then live at `https://YOUR-NAME-brand-risk-index.hf.space`.

Free Spaces sleep after 48 hours without visitors and wake up on the next visit (about a minute). To make the GitHub Pages copy use the live server too, set `window.BRI_API_BASE` in `js/config.js` to the Space URL.

---

## Architecture

![Architecture](docs/architecture.png)

Also available as [PDF](docs/architecture.pdf) and [SVG](docs/architecture.svg).

---

## Project Structure

```
brand-risk-index/
├── index.html                  # Dashboard (8 tabs)
├── setup.bat / setup.sh        # One-time install
├── start.bat / start.sh        # Start server + dashboard on http://localhost:8000
├── Dockerfile                  # Container for Hugging Face Spaces / any Docker host
├── docs/                       # Architecture diagram (PNG, PDF, SVG)
├── css/style.css
├── js/
│   ├── config.js               # Where the API lives (for static copies)
│   ├── data.js                 # Latest results (written by the backend)
│   ├── live.js                 # Live refresh, polling, company modal additions
│   ├── search.js               # Company Search (any company)
│   ├── sources.js              # Source comparison
│   ├── mcdm.js                 # AHP weights, CRITIC, sensitivity
│   ├── validation.js           # Back-test, FinBERT labelling, headline scorer
│   └── overview.js, register.js, modal.js, compare.js, action.js, helpers.js, nav.js, main.js
└── backend/
    ├── api.py                  # FastAPI server: REST API, live refresh, dashboard
    ├── config.py               # Weights, feeds, sector multipliers, scoring parameters
    ├── run_pipeline.py         # CLI runner
    ├── data/                   # companies.json, company_directory.json, incidents.json, labels.json
    ├── nlp/                    # text_ingestion.py, finbert_pipeline.py, crisis_classifier.py
    ├── mcdm/                   # ahp.py, topsis.py, critic.py, sensitivity.py
    ├── engine/                 # risk_scorer.py, live_scoring.py, backtest.py, evaluation.py
    ├── tests/                  # Unit tests
    └── output/                 # latest.json, backtest.json
```

---

## Mathematical Model

FinBERT scores every headline → four criteria (0–100, report Table III) → AHP weights → TOPSIS
distance from a fixed lowest-risk baseline and a fixed maximum-crisis profile:

$$\text{Risk Index} = \frac{D^+}{D^+ + D^-} \times 100$$

### 1. AHP Priority Weights ($w_i$)
Computed from the pairwise matrix in `backend/mcdm/ahp.py` (Saaty scale, rows C1–C4: `[1,2,3,4]`, `[1/2,1,2,3]`, `[1/3,1/2,1,2]`, `[1/4,1/3,1/2,1]`):
* **$C_1$ (Severity):** 0.4658
* **$C_2$ (Reach):** 0.2771
* **$C_3$ (Recoverability):** 0.1611
* **$C_4$ (Criticality):** 0.0960

$\lambda_{max} = 4.031$, $CI = 0.0103$, $CR = 0.0115 < 0.10$ (consistent). These are the weights the engine uses;
`config.py` lists the same values (the earlier 0.35 / 0.28 / 0.22 / 0.15 did not match the matrix — report Table IV).
`backend/tests/test_mcdm.py` checks they stay in sync.

### 2. Criteria (live mode)
* $w_i = 0.5^{\,age_i / 72h}$ — time decay
* $s = \dfrac{\sum w_i \max(0, -score_i)}{\sum w_i + 2}$ over opinionated (non-neutral) headlines — negative effective sentiment (2 neutral pseudo-headlines damp tiny samples)
* $C_1 = \text{clip}_{[5,100]}(100\,s)$
* $C_2$ = Viral 100 / High 75 / Medium 50 / Low 25 from recency-weighted negative volume and the number of outlets carrying negative stories
* $C_3 = \text{clip}_{[10,100]}(0.6\,C_1 + 0.4\,C_2)$
* $C_4 = \text{clip}_{[10,100]}(m_k\,C_1)$, sector multiplier $m_k$ from 0.65 (FMCG) to 1.15 (FinTech)

### 3. TOPSIS
* **Normalisation:** criteria already share a 0–100 scale, so $r_{ij} = x_{ij}/100$
* **Weighted Matrix:** $v_{ij} = w_j \cdot r_{ij}$
* **Ideal Solutions:** $A^+$ = lowest-risk baseline (5, 25, 13, 10), $A^-$ = maximum crisis exposure (100, 100, 100, 100). Because they are fixed, a searched company and the monitored companies are on one scale. (Classic vector-normalised, set-relative TOPSIS is kept as `mode="relative"`; it pushed every company to 0 or 100.)
* **Euclidean Distances:** $D^+_i = \sqrt{\sum (v_{ij} - A^+_j)^2}$, $D^-_i = \sqrt{\sum (v_{ij} - A^-_j)^2}$
* **Bands (Table V):** Low < 40 (background logging), Moderate 40–<70 (assign analyst · SEBI check · draft statement), Critical ≥ 70 (executive crisis protocol · legal review · PR response)
* **Confidence range:** 5–95% of the index over 200 bootstrap resamples of the headlines

### 4. Additions from the report's remaining work / recommendations
* **Crisis-event classifier** (`nlp/crisis_classifier.py`): rule-based issue type per headline (Regulatory Action, Fraud & Governance, Tax Dispute, Legal, Data & Cyber, Safety & Product, …) and regulator mentions (RBI, SEBI, USFDA, …). Sets the "dominant issue".
* **Explanations:** per-criterion share of the distance from the baseline, and each headline's share of the severity score.
* **Sensitivity analysis** (`mcdm/sensitivity.py`): every pairwise judgement ±1 Saaty step, ±10/25/50% one-at-a-time weight changes, 1,000-draw Monte Carlo; reports Spearman rank correlation, band changes and per-company index ranges.
* **CRITIC objective weights** (`mcdm/critic.py`) compared with and blended into the AHP weights.
* **Back-test** (`engine/backtest.py`, `data/incidents.json`): 12 documented Indian incidents, incident week vs. the same week 60 days earlier, against sentiment-only and mention-volume baselines. Pilot scale.
* **FinBERT accuracy check** (`engine/evaluation.py`): hand-label headlines in the Validation tab; accuracy, macro-F1 and confusion matrix for FinBERT vs. the keyword heuristic.
* **Unit tests** for AHP, TOPSIS, bands, scoring, classifier, CRITIC and sensitivity.

Not done (future work in the report): independent indicators for C3/C4, a multilingual model (MuRIL / XLM-R) for Hindi/Hinglish, an expert survey for the AHP matrix, and a usability study.

---

## How to Run

### 1. Full app (live news, search, all tabs)
```bash
setup.bat   # first time only
start.bat
```
Then open http://localhost:8000. The server refreshes live news every 15 minutes
(`REFRESH_MINUTES`, `LOOKBACK_HOURS`, `USE_FINBERT`, `DECAY_HALF_LIFE_HOURS` can be set as environment variables).
Opening `index.html` directly still works, but only with the stored data (no search or live refresh).

Dashboard tabs: Overview · **Company Search** (any company, live or past dates) · Source Comparison · Risk Register · Compare · **MCDM** (live weights, CRITIC, sensitivity) · Action Engine · **Validation** (back-test, FinBERT labelling, one-headline scorer).

### 2. Tests
```bash
py -3 -m unittest discover -s backend/tests -v
```

### 3. Pipeline CLI
```bash
py -3 backend/run_pipeline.py --eval-ahp
py -3 backend/run_pipeline.py --test-bert "RBI queries fintech platform on digital lending compliance"
py -3 backend/run_pipeline.py --mode live --sync-frontend
```

### 4. REST API (FastAPI, docs at http://localhost:8000/docs)
* `GET /api/companies`, `/api/companies/{id}`, `/api/sectors`, `/api/compare?ids=BR-101,BR-104`
* `GET /api/search?company=Swiggy&hours=48` — brand-risk assessment for any company; `&date_from=2024-01-31&date_to=2024-02-04` for a past period
* `GET /api/resolve?q=hul` — company name suggestions / sector auto-detection
* `GET /api/mcdm/ahp`, `/api/mcdm/weights?alpha=0.5`, `/api/mcdm/sensitivity`
* `GET /api/backtest`, `POST /api/backtest/run`
* `GET /api/eval/sample`, `POST /api/eval/label`, `GET /api/eval/metrics`
* `POST /api/score-text` — FinBERT score + crisis category for one headline
* `GET /api/live/status`, `POST /api/live/refresh`, `GET /api/headlines`, `/api/sources`, `/api/source-matrix`
* `POST /api/watchlist`, `DELETE /api/watchlist/{id}`
* `POST /api/recalculate`
