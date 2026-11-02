# AI + MCDM Brand Image Risk Index

A real-time decision-support system and analytics platform designed to detect, evaluate, and mitigate corporate reputational threats for Indian enterprises using **FinBERT Sentiment NLP** and the **AHP-TOPSIS Multi-Criteria Decision-Making (MCDM)** engine.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Live Text Ingestion             |
                      | Google News RSS, Moneycontrol, Feeds  |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       FinBERT NLP Pipeline            |
                      | Sentiment Intensity & Probabilities   |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       MCDM Weighting Engine           |
                      | AHP Priority Weights + TOPSIS Ranking |
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |     Interactive Web Dashboard         |
                      |  Compare, Risk Register, Action Engine|
                      +---------------------------------------+
```

---

## Project Structure

```
fdetection/
├── index.html                  # Minimalist, clean dashboard (no AI-vibe styling)
├── css/
│   └── style.css               # Clean Bloomberg-terminal inspired dark mode theme
├── js/
│   ├── data.js                 # Enterprise dataset (can be synced from backend)
│   ├── helpers.js              # Color palette, metric calculations, chart registry
│   ├── nav.js                  # Seamless sidebar tab routing
│   ├── overview.js             # Sector averages, stacked bars & top critical list
│   ├── register.js             # Live searchable, filterable company risk table
│   ├── modal.js                # Detail modal with 4-criteria MCDM radar chart
│   ├── compare.js              # Multi-company comparison & grouped bar charts
│   ├── mcdm.js                 # Mathematical formula & TOPSIS step guide
│   ├── action.js               # Threshold action rules, alert feed & risk donut
│   └── main.js                 # Application bootstrap
│
└── backend/
    ├── requirements.txt        # Python dependencies
    ├── config.py               # Central paths, weights, and thresholds
    ├── api.py                  # Flask REST API with CORS support
    ├── run_pipeline.py         # CLI runner for FinBERT, AHP, and TOPSIS
    │
    ├── data/
    │   └── companies.json      # Enterprise profiles, search terms, and crisis feeds
    │
    ├── nlp/
    │   ├── finbert_pipeline.py # ProsusAI/finbert model & heuristic fallback
    │   └── text_ingestion.py   # RSS & Google News search collector
    │
    ├── mcdm/
    │   ├── ahp.py              # 4x4 Pairwise Matrix, weights, CI, & CR check
    │   └── topsis.py           # Vector normalisation, A+/A- ideals, & Closeness
    │
    ├── engine/
    │   └── risk_scorer.py      # End-to-end pipeline orchestrator & sync utility
    │
    └── output/                 # Timestamped JSON outputs and latest.json
```

---

## Mathematical Model

The composite risk equation is derived from Analytic Hierarchy Process (AHP) and TOPSIS:

$$\text{Risk Index} = \sum_{i=1}^{n} w_i \cdot c_i$$

### 1. AHP Priority Weights ($w_i$)
Derived from expert pairwise judgment:
* **$C_1$ (Severity):** 0.35 — FinBERT negative sentiment depth & regulatory violation risk.
* **$C_2$ (Reach):** 0.28 — Audience volume, virality velocity, and media tier.
* **$C_3$ (Recoverability):** 0.22 — PR turnaround difficulty and decay rate.
* **$C_4$ (Criticality):** 0.15 — Impact on SEBI, institutional investors, and public trust.

Consistency Ratio ($CR$): **$0.011 < 0.10$** (Mathematically Consistent).

### 2. TOPSIS Multi-Criteria Ranking
* **Normalisation:** $r_{ij} = \frac{x_{ij}}{\sqrt{\sum x_{ij}^2}}$
* **Weighted Matrix:** $v_{ij} = w_j \cdot r_{ij}$
* **Ideal Solutions:** $A^+$ (lowest risk baseline), $A^-$ (maximum crisis exposure).
* **Euclidean Distances:** $D^+_i = \sqrt{\sum (v_{ij} - A^+_j)^2}$, $D^-_i = \sqrt{\sum (v_{ij} - A^-_j)^2}$
* **Risk Closeness:** $\text{Risk Index} = \frac{D^+_i}{D^+_i + D^-_i} \times 100$

---

## How to Run

### 1. Frontend Web Dashboard
Simply open `index.html` in any browser:
* Double-click `index.html` or run `start index.html` in PowerShell.
* Search companies, view sector charts, and compare up to 4 companies side-by-side.

### 2. Python Backend & Pipeline CLI

#### Run AHP Consistency Verification:
```bash
py -3 backend/run_pipeline.py --eval-ahp
```

#### Test FinBERT on Any News Headline:
```bash
py -3 backend/run_pipeline.py --test-bert "RBI queries fintech platform on digital lending compliance"
```

#### Execute Full Pipeline & Sync Directly to Dashboard:
```bash
# Fast execution using local crisis dataset:
py -3 backend/run_pipeline.py --mode mock --offline --sync-frontend

# Live web ingestion and FinBERT neural scoring (downloads ProsusAI/finbert on first run):
py -3 backend/run_pipeline.py --mode live --sync-frontend
```

### 3. Running the REST API Server
```bash
py -3 backend/api.py
```
API endpoints available at `http://127.0.0.1:5000`:
* `GET /api/companies`: Retrieve company risk registers and MCDM scores
* `GET /api/sectors`: Aggregated sectoral risk profiles
* `GET /api/mcdm/ahp`: AHP pairwise matrix, weights, and consistency metrics
* `POST /api/score-text`: Score arbitrary news articles using FinBERT
* `POST /api/recalculate`: Trigger pipeline re-computation
* `GET /api/compare?ids=BR-101,BR-104`: Side-by-side company evaluation

