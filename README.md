---
title: NSE Brand Risk Monitor
emoji: 📊
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
short_description: Brand risk for NSE companies from stock moves + news (AHP-TOPSIS)
---

# NSE Brand Risk Monitor (AI + MCDM Brand Image Risk Index)

A daily **brand risk score from 0 to 100** for companies listed on the **National Stock Exchange of India (NSE)**, by default the 50 companies of the **NIFTY 50**. The score is built from two kinds of evidence:

1. **Stock effect.** How unusually the share price behaves *after removing what the NIFTY 50 and the company's sector peers did*.
2. **News.** How negative the recent headlines are, when there are any, scored with **FinBERT** or a finance word list.

These five signals are weighted with **AHP** and combined with **TOPSIS**. The score is stored every trading day so each company can be tracked over time. Each score is explained in plain English, stress-tested (CRITIC weights, sensitivity analysis) and validated with a back-test on documented incidents.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-GitHub%20Pages-2f81f7?style=for-the-badge&logo=github)](https://se23uari120.github.io/brand-risk-index/)
[![Source Code](https://img.shields.io/badge/Repository-GitHub-161b22?style=for-the-badge&logo=github)](https://github.com/se23uari120/brand-risk-index)

* **Online demo (static: stored results, updated daily, no search):** https://se23uari120.github.io/brand-risk-index/
* **Full app (live re-scoring, Company Search, validation tools):** run it locally with the two commands below, or host it (see [Hosting](#hosting))

> Not investment advice. This is a monitoring tool for brand and reputation risk.

(The block between the `---` lines at the top is only used if the app is hosted on Hugging Face Spaces.)

---

## Contents

- [Quick start](#quick-start)
- [What you see](#what-you-see)
- [How the score works](#how-the-score-works)
- [Robustness and validation](#robustness-and-validation)
- [Daily tracking and the live server](#daily-tracking-and-the-live-server)
- [Hosting](#hosting)
- [Architecture](#architecture)
- [Command line](#command-line)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [REST API](#rest-api)
- [Changes compared with the report](#changes-compared-with-the-report)
- [Data sources and limitations](#data-sources-and-limitations)

---

## Quick start

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

Then open **http://localhost:8000**. `setup` runs once and installs PyTorch (CPU), FinBERT, FastAPI and the core packages into `.venv`. After that only `start` is needed. FinBERT (~440 MB) downloads on the first start, and the first scoring pass takes about 2 minutes.

**With Docker:** `docker build -t brand-risk .` then `docker run -p 7860:7860 brand-risk` → http://localhost:7860

**Without the server:** opening `index.html` directly works too, showing the stored results in `js/data.js`. To refresh them you only need three packages:

```bash
pip install -r backend/requirements.txt
```

```bash
py -3 backend/run_pipeline.py
```

---

## What you see

| Tab | What it shows |
|---|---|
| **Overview** | Counts of High / Moderate companies, the highest-risk companies with a one-line reason and their main issue, the biggest risers this week, the most negative news, what the bad news is about (issue types) and average risk by sector. |
| **All companies** | Searchable, sortable table: score, level, 1-week change, company-specific share move, news count, 30-day trend. |
| **Company panel** (click any company) | The score in plain English, a 90% range, the main issue and regulators named, the five signals with their evidence, the risk history, price vs NIFTY 50, the company-specific performance line, the headlines with sentiment and issue type, and the full TOPSIS calculation. |
| **Search** *(server)* | Any NSE-listed company (name, brand or symbol), live or **as of a past day**. It is scored exactly like the tracked companies and can be added to the watchlist. |
| **Compare** | Up to four companies side by side. |
| **MCDM** | AHP vs CRITIC vs blended vs equal weights, an interactive blend slider, the CRITIC inputs, judgement perturbation, one-at-a-time weight changes and 1,000 Monte Carlo weightings. |
| **Validation** | The incident back-test with baselines, the sentiment check against human labels, a one-headline scorer and where the news comes from. Labelling, re-running the back-test and the scorer need the server. |
| **How it works** | The whole method explained with today's real numbers. AHP weights are recomputed in the browser, and there is a TOPSIS worked example for any company. |

It works on phones, in light and dark mode, and every chart has a table view. With the server running, a green **Live** badge appears in the header. Click it to re-score now.

---

## How the score works

A brand problem shows up in two places: **investors sell the shares more than the market explains**, and **the press writes negative stories**. The monitor measures both, and **removes market-wide and sector-wide moves first**, because a falling sector is not a problem with one brand.

```
 NSE prices (Yahoo) ──► two-factor model ──► C1 Market reaction ─┐
                                             C2 Trading stress   │
                                             C3 Lingering damage ├─► AHP weights ─► TOPSIS (fixed ideals) ─► score 0–100 ─► level
 Google News + outlet feeds ──► relevance ──► C4 News tone        │                                              │
      ──► sentiment (FinBERT) + issue type    C5 Negative coverage┘                                              ▼
                                                                                              daily history · dashboard · API
```

### Step 1: Collect

* **Prices:** one year of daily split- and dividend-adjusted closes and volumes from Yahoo Finance's public chart data for `SYMBOL.NS` and the NIFTY 50 (`^NSEI`). Past periods are downloaded for search and the back-test.
* **News:** a Google News search per company (live: last 50 days; past: `after:`/`before:`), plus, for the latest 3 days, the RSS feeds of Business Standard, Economic Times, Livemint, Hindu BusinessLine, CNBC-TV18, NDTV Profit and Indian Express.
* **Relevance:** a headline must name the company (with tuned name variants) and not a similarly named one (e.g. "SBI Life" for SBI). Market wrap-ups ("Sensex, Nifty fall…") and duplicates are dropped, and HTML entities are decoded.
* **Sentiment:** each headline is scored −1…+1 by **FinBERT** (`ProsusAI/finbert`: P(positive) − P(negative)), or by a transparent finance word list when FinBERT isn't installed. Headlines at ≤ −0.15 count as negative and ≥ +0.15 as positive.
* **Issue type:** a rule-based **crisis-event classifier** tags each headline: Regulatory Action, Fraud & Governance, Tax Dispute, Legal & Litigation, Data & Cyber, Safety & Product, Service Outage, Labour & Protest, Leadership Change, Financial Distress, ESG & Environment or Market & Earnings. It also records the regulators named (RBI, SEBI, USFDA, …). This explains the score; it does not change it.

### Step 2: The five signals (0–100 risk points each)

**Expected-return model (C1, C3).** This is estimated per stock over the 120 trading days that end 20 days before the scored day:

```
expected return = β · r_NIFTY + γ · (r_peers − r_NIFTY)        abnormal return AR = actual − expected
```

`r_peers` is the average of the company's sector peers on the watchlist (itself excluded; at least 3 tracked companies in the sector, otherwise γ = 0). Both coefficients are shrunk toward 1 (`0.67·b + 0.33`). σ is the stock's normal daily abnormal-return noise. So if every IT stock falls 5% on a sector-wide worry, Infosys's abnormal return is about zero.

**News weighting (C4, C5).** Each headline in the last 7 days has a recency weight `w = 0.5^(age / 72 h)`.

| # | Signal | Question | Formula → risk points | AHP weight |
|---|---|---|---|---|
| C1 | **Market reaction** | Did the shares fall more than the market and sector explain? | z₅ = CAR₅/(σ√5), z₂₀ = CAR₂₀/(σ√20) → `100·clip((max(−z₅,−z₂₀) − 1)/2)`: 0 down to −1σ, 50 at −2σ, 100 at −3σ | **36.9%** |
| C2 | **Trading stress** | Is it traded unusually nervously? | `½·clip((vol10/vol90 − 1)/1.5) + ½·clip((volume5/volume60 − 1)/2)`, × 0.25 if the stock is beating expectations | **10.9%** |
| C3 | **Lingering damage** | Has company-specific damage built up and stayed? | gap of the running Σ AR below its 3-month best, in units of σ√63 → `100·clip((gap − 1)/2)` | **20.6%** |
| C4 | **News tone** | How negative is the opinionated coverage? | `100 · Σ wᵢ·max(0,−sᵢ) / (Σ wᵢ + 2)` over **non-neutral** headlines. Routine neutral news does not water a crisis down; the 2 pseudo-headlines stop one stray story spiking it. 0 with no news. | **20.6%** |
| C5 | **Negative coverage** | How much negative coverage? | `100 · (1 − e^(−Σ wᵢ over negative headlines / 5))`: 1 fresh story → 18, 5 → 63, 10 → 86 | **10.9%** |

Stock behaviour carries **68%** of the weight and news **32%**. With no news, the score rests on stock behaviour alone.

### Step 3: AHP weights

| Row is … × as important as column | C1 | C2 | C3 | C4 | C5 | **Weight** |
|---|---|---|---|---|---|---|
| C1 Market reaction | 1 | 3 | 2 | 2 | 3 | **36.9%** |
| C2 Trading stress | 1/3 | 1 | 1/2 | 1/2 | 1 | **10.9%** |
| C3 Lingering damage | 1/2 | 2 | 1 | 1 | 2 | **20.6%** |
| C4 News tone | 1/2 | 2 | 1 | 1 | 2 | **20.6%** |
| C5 Negative coverage | 1/3 | 1 | 1/2 | 1/2 | 1 | **10.9%** |

The weights are the principal eigenvector, with λmax = 5.0133, CI = 0.0033, RI(5) = 1.12 and **CR = 0.0030 < 0.10**, so the judgements are consistent. Print it yourself with `py -3 backend/run_pipeline.py --eval-ahp`.

### Step 4: TOPSIS with fixed ideal points

`r = points/100` → `v = w·r` → **A⁺ = 0** (safest possible), **A⁻ = 100 on every signal** (worst possible) → `D⁺ = √Σ v²`, `D⁻ = √Σ (w − v)²` → **score = 100 · D⁺ / (D⁺ + D⁻)**.

* **Fixed ideals keep days comparable.** Classic TOPSIS uses the best and worst company of the day, which forces someone to 0 and someone to 100. With fixed ideals, a 40 today means the same as a 40 last month, and searched companies share the same scale.
* **One severe signal is not averaged away.** Market reaction alone at 100 gives about 53, where a weighted average would give 37. Every signal at 50 gives exactly 50.

### Step 5: Levels, actions and the 90% range

| Level | Score | Prescribed action |
|---|---|---|
| **High** | 50 – 100 | Executive crisis protocol: legal review, investor-relations alert, real-time PR response |
| **Moderate** | 30 – 50 | Assign an analyst, check disclosure (SEBI) obligations, draft a holding statement |
| **Low** | 0 – 30 | Background logging and routine monitoring; no escalation |

**90% range:** each score is recomputed for 200 bootstrap resamples of the week's headlines. The middle 90% shows how much the score depends on which stories happened to be picked up.

**Example (NSE close, 19 Nov 2026).** Tata Motors PV scored **71.6 (High, 90% range 70–73)**. The shares fell 13.4% more than the market and sector explained (−3.8σ) after Jaguar Land Rover cut its outlook, and 24 of 42 headlines were negative. TCS fell 4.1% that week, but its sector peers fell 4.5%, so it correctly stayed **Low**.

---

## Robustness and validation

**Weights (MCDM tab, data as of 19 Nov 2026).** All rank-agreement figures are Spearman ρ with the AHP ranking.

| Weighting | C1 | C2 | C3 | C4 | C5 | Rank agreement | Companies changing level |
|---|---|---|---|---|---|---|---|
| AHP | 36.9% | 10.9% | 20.6% | 20.6% | 10.9% | 1.000 | 0 |
| CRITIC (objective) | 13.3% | 13.7% | 26.4% | 22.2% | 24.5% | 0.949 | 5 |
| 50/50 blend | 25.1% | 12.3% | 23.5% | 21.4% | 17.7% | 0.985 | 0 |
| Equal | 20% | 20% | 20% | 20% | 20% | 0.977 | 3 |

Moving any single AHP judgement one Saaty step keeps ρ ≥ 0.995 with no level changes. Changing any one weight by ±10–50% keeps ρ ≥ 0.986 with at most one level change. Over 1,000 Monte Carlo weightings the mean ρ is 0.987 (worst 5%: 0.968). The ranking is robust to the weights; the CRITIC weighting mainly shifts weight from Market reaction to the news signals.

**Back-test (Validation tab).** There are 12 documented Indian incidents. Each company is scored point-in-time at the end of the incident week and on a control day 60 days earlier, from the same data, alongside four simpler methods:

| Method | Incident scored higher than control | Hit rate (≥ 30) | False alarms | Mean incident / control |
|---|---|---|---|---|
| **Risk index (stock + news)** | **92%** | **42%** | 17% | **41.5 / 10.5** |
| Stock signals only | 67% | 42% | 17% | 29.5 / 9.3 |
| News signals only | 83% | 0% | 0% | 16.4 / 2.1 |
| Average sentiment only | 83% | 17% | 0% | 22.1 / 1.9 |
| Number of headlines | 83% | – | – | 26.2 / 5.7 |

These results are from the word-list sentiment engine. Detected incidents: Paytm (RBI, 79), Kotak Mahindra Bank (RBI, 75), IIFL Finance (RBI, 79), Adani Enterprises (Hindenburg, 70) and Adani Green (US indictment, 80). Missed: events the market shrugged off, such as the Zomato uniform backlash (rolled back the next day) and the JLR cyber attack. With 12 incidents this shows direction, not statistical significance.

**Sentiment check.** With the server running, hand-label headlines in the Validation tab (the model's answer is hidden). Accuracy, macro-F1 and the confusion matrix are reported for the word list and FinBERT. Labels are stored in `backend/data/labels.json`.

**Unit tests (37):**

```bash
py -3 -m unittest discover -s backend/tests -v
```

They cover:
- AHP weights, consistency and the eigenvector
- TOPSIS properties and the levels
- every signal formula
- the stock model on synthetic data (a sector-wide fall must not be flagged; a company-specific one must)
- news decay and the opinionated-only tone
- relevance filtering and HTML decoding
- sentiment, the crisis classifier, CRITIC and the sensitivity analysis
- the shared company scorer and the evaluation metrics

---

## Daily tracking and the live server

* **Daily job.** `.github/workflows/update-risk-data.yml` runs every weekday at **16:45 IST**, after the 15:30 NSE close. It runs the unit tests and the pipeline (with FinBERT on CPU), then commits `js/data.js` and `backend/output/*.json`, so the GitHub Pages site updates itself. Run it by hand from the *Actions* tab, optionally with `backtest: true`. Under **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions** so the job can commit.
* **Point-in-time.** Each day uses only prices up to that day's close and headlines published up to that day. The first run backfills 30 trading days. Afterwards only the last 5 days are refreshed, and past days stay frozen. Up to 400 trading days are kept in `backend/output/history.json`.
* **Live server.** `start.bat` / `start.sh` / Docker re-scores every `REFRESH_MINUTES` (default 60). Open dashboards pick up new scores automatically. Environment variables: `SENTIMENT=auto|finbert|lexicon`, `REFRESH_MINUTES`, `LIVE_REFRESH=false`, `DECAY_HALF_LIFE_HOURS`, `HOST`, `PORT`.

---

## Hosting

GitHub Pages hosts the static dashboard, kept current by the daily job. Company Search and the other server features need the Python server. To put the full app online, run the `Dockerfile` on a host with about **2 GB RAM** (FinBERT + PyTorch). As of November 2026:

| Option | Cost | Notes |
|---|---|---|
| Hugging Face Spaces (Docker) | PRO plan, $9/month | Free accounts can no longer host Docker Spaces. Steps below. |
| Google Cloud Run | free tier for light use | Needs a billing account; set memory to 2 GiB. |
| Your own PC + a tunnel (e.g. Cloudflare quick tunnel) | free | Works only while the PC and `start.bat` are running. |

**Hugging Face Spaces** (with PRO):
1. Sign in: `.venv\Scripts\hf auth login` (Windows) or `.venv/bin/hf auth login`.
2. Create the Space and upload the code:
   ```bash
   hf repos create YOUR-NAME/brand-risk-index --type space --space-sdk docker --public
   hf upload YOUR-NAME/brand-risk-index . . --repo-type space --exclude ".venv/*" "backend/models/*" "backend/cache/*" ".git/*" "**/__pycache__/*"
   ```
3. The first build takes about 5–10 minutes. The app is then at `https://YOUR-NAME-brand-risk-index.hf.space`.

Once the full app is hosted anywhere, set `window.BRI_API_BASE` in `js/config.js` to its URL. The GitHub Pages copy will then use it for live data and search too.

---

## Architecture

![Architecture](docs/architecture.png)

Also available as [PDF](docs/architecture.pdf) and [SVG](docs/architecture.svg).

---

## Command line

| Command | What it does |
|---|---|
| `py -3 backend/run_pipeline.py` | Full run: prices + news, score all companies, update history and the dashboard (~2 min) |
| `py -3 backend/run_pipeline.py --offline` | Re-score from the last downloads (no network) |
| `py -3 backend/run_pipeline.py --limit 5` | Quick test on 5 companies (nothing saved) |
| `py -3 backend/run_pipeline.py --backtest` | Re-run the 12-incident back-test (~4 min) and show it on the dashboard |
| `py -3 backend/run_pipeline.py --search Swiggy` | Score any NSE company now (`--as-of 2024-02-04` for a past day) |
| `py -3 backend/run_pipeline.py --eval-ahp` | Print the AHP matrix, weights and consistency |
| `py -3 backend/run_pipeline.py --test-headline "RBI bars XYZ Bank…"` | Sentiment, issue type and regulators for one headline |
| `--sentiment finbert\|lexicon`, `--no-feeds`, `--reset-history`, `--no-export` | Options for the full run |

---

## Configuration

| What | Where |
|---|---|
| Tracked companies: NSE symbol, sector, news query, name variants, exclusions | `backend/data/watchlist.json` (or "Add to watchlist" in Search) |
| Brand aliases used by Search (e.g. Paytm → One97) | `backend/data/company_directory.json` |
| Back-test incidents | `backend/data/incidents.json` |
| Windows, news decay, outlet feeds, level thresholds, actions, history length, server settings | `backend/config.py` |
| AHP pairwise judgements | `backend/mcdm/ahp.py` (`DEFAULT_PAIRWISE`) |
| Signal formulas and their explanations (shown in the dashboard) | `backend/engine/criteria.py` |
| Where a static copy finds the server | `js/config.js` (`window.BRI_API_BASE`) |

---

## Project structure

```
brand-risk-index/
├── index.html                    # Dashboard (7 tabs, no build step)
├── setup.bat / setup.sh          # One-time install into .venv (CPU PyTorch, FinBERT, FastAPI)
├── start.bat / start.sh          # Server + dashboard on http://localhost:8000, hourly re-scoring
├── Dockerfile                    # Container for Hugging Face Spaces / Cloud Run / any Docker host
├── docs/                         # Architecture diagram (PNG, PDF, SVG)
├── css/style.css                 # Light/dark design tokens and layout
├── js/
│   ├── config.js                 # Where the API lives (for static copies)
│   ├── data.js                   # GENERATED: scores, signals, history, headlines, MCDM, back-test
│   ├── util.js · charts.js       # Formatting, explanations, themed Chart.js wrappers
│   ├── live.js                   # Server detection, live refresh
│   ├── overview.js · companies.js · detail.js · compare.js
│   ├── search.js                 # Company Search (server)
│   ├── mcdm.js                   # AHP vs CRITIC, blend slider, sensitivity
│   ├── validation.js             # Back-test, sentiment check, headline scorer, sources
│   ├── method.js                 # "How it works" with live AHP / TOPSIS examples
│   └── app.js                    # Routing (#company/TMPV deep links), theme, bootstrap
├── .github/workflows/update-risk-data.yml   # Daily tests + update after the NSE close
└── backend/
    ├── run_pipeline.py           # Command-line runner
    ├── api.py                    # FastAPI server: dashboard, live mode, search, validation API
    ├── config.py                 # All tunable settings
    ├── requirements.txt          # core: numpy, pandas, requests
    ├── requirements-api.txt      # + fastapi, uvicorn
    ├── requirements-finbert.txt  # + torch, transformers
    ├── data/                     # watchlist, company_directory, incidents, labels
    ├── market/
    │   ├── nse_prices.py         # Yahoo Finance download (1 year or a past period) + cache
    │   ├── stock_signals.py      # Two-factor model, abnormal returns, z-scores, stress, drawdown
    │   └── symbols.py            # Company lookup for search (watchlist → directory → Yahoo)
    ├── nlp/
    │   ├── news.py               # Google News + relevance filtering (live or past window)
    │   ├── feeds.py              # Outlet RSS feeds + Moneycontrol sitemap
    │   ├── sentiment.py          # FinBERT and finance word-list engines
    │   └── crisis_classifier.py  # Issue types + regulators
    ├── mcdm/
    │   ├── ahp.py                # Eigenvector weights + consistency ratio
    │   ├── topsis.py             # TOPSIS with fixed ideal points
    │   ├── critic.py             # CRITIC objective weights
    │   └── sensitivity.py        # Judgement / one-at-a-time / Monte Carlo sensitivity
    ├── engine/
    │   ├── criteria.py           # The five signals (formulas + explanations)
    │   ├── assess.py             # Scores one company (shared by pipeline, search, back-test)
    │   ├── risk_scorer.py        # Daily pipeline for the watchlist
    │   ├── search.py             # Company Search
    │   ├── backtest.py           # Incident back-test with baselines
    │   └── evaluation.py         # Sentiment accuracy against human labels
    ├── tests/test_model.py       # 37 unit tests
    └── output/                   # latest.json, history.json, backtest.json
```

---

## REST API

Start the server (`start.bat`), then see the interactive docs at http://localhost:8000/docs.

| Endpoint | Returns |
|---|---|
| `GET /api/data` | Everything the dashboard shows (same as `js/data.js`) |
| `GET /api/live/status` · `POST /api/live/refresh` | Live-mode status · re-score now |
| `GET /api/companies?sector=&level=&q=` · `GET /api/companies/{symbol}` | Ranked list · one company in full |
| `GET /api/search?q=Swiggy&as_of=2024-02-04` | Assessment of any NSE company, now or as of a past day |
| `GET /api/resolve?q=pay` | Search-box suggestions (NSE only) |
| `GET/POST /api/watchlist` · `DELETE /api/watchlist/{symbol}` | Tracked companies · add · remove a company you added |
| `GET /api/mcdm` · `GET /api/method` | CRITIC and sensitivity · signal definitions and AHP |
| `GET /api/backtest` · `POST /api/backtest/run` | Back-test results and progress · re-run |
| `GET /api/eval/sample` · `POST /api/eval/label` · `GET /api/eval/metrics` · `DELETE /api/eval/labels` | Sentiment labelling |
| `POST /api/score-headline` | Sentiment, issue type and regulators for `{"text": "…"}` |
| `GET /api/crisis-categories` | The issue types |

---

## Changes compared with the report

The first version (the report's Tables III–V) scored companies from **news alone** with four criteria. This version keeps the AHP + TOPSIS framework and everything built for the report's remaining work, and changes the evidence:

* **Criteria.** Severity, Reach, Recoverability and Criticality were all derived from news, and C3 and C4 were formulas of C1 and C2. They are replaced by **five independently measured signals**: three from company-specific stock behaviour and two from news. This also addresses the open item "independent indicators for C3/C4".
* **Universe.** NSE-listed companies (NIFTY 50) with their share prices; Company Search covers any NSE-listed company.
* **Weights.** A new 5×5 AHP matrix (CR 0.003) replaces the 4×4 matrix (CR 0.0115).
* **Levels.** Low < 30, Moderate 30–50, High ≥ 50, replacing Low < 40, Moderate 40–70, Critical ≥ 70. Company-specific evidence produces lower everyday scores, so the cut-offs are stricter. The prescribed actions are the same.
* **Kept from the report's work:**
  - news time decay (72 h half-life), with neutral headlines not diluting severity and the two-pseudo-headline damping
  - fixed TOPSIS reference profiles and the bootstrap range
  - the crisis-event classifier
  - CRITIC weights and the sensitivity analysis
  - the incident back-test, now with stock-only and news-only baselines
  - the FinBERT labelling check
  - Company Search, the watchlist, the setup / start scripts and the Docker deployment

---

## Data sources and limitations

* **Prices** come from Yahoo Finance's public chart data. It is unofficial and can be late or revised. The newest bar is taken from Yahoo's final market quote once the session has closed.
* **Headlines** come from Google News RSS (for personal, non-commercial use) and the outlets' own RSS feeds. Only headlines are analysed, not full articles. Moneycontrol's news sitemap refused automated access (HTTP 403) on 20 Nov 2026, so Moneycontrol stories arrive through Google News. Times of India's feed was empty that day.
* **The word-list sentiment engine is crude.** For example, it reads "court sets aside sanction to prosecute" as negative because of "scam". FinBERT is better; the daily job and `setup` use it.
* **The issue classifier is keyword-based.** It explains coverage but can mislabel. For example, arrests in the Tanishq jewellery heist were tagged Fraud & Governance for Titan.
* **A stock fall is not always a brand problem.** Results, guidance or analyst calls also move prices, so read the headlines in each company's panel.
* **A Low score does not mean no reputational issue.** If the market shrugs off bad news, the stock signals stay quiet. The Overview's "Most negative news" list catches those cases (e.g. a fatal accident at an NTPC site with no share-price reaction).
* **Sector peers come from the watchlist.** Sectors with fewer than 3 tracked companies are compared with the NIFTY 50 only.
* **The back-test is a 12-incident pilot.** It shows direction, not statistical significance.
