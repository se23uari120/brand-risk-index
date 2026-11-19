# NSE Brand Risk Monitor

A daily **brand risk score from 0 to 100** for companies listed on the **National Stock Exchange of India (NSE)**, by default the 50 companies of the **NIFTY 50**. The score is built from two kinds of evidence:

1. **Stock effect.** How unusually the share price is behaving *after removing what the NIFTY 50 and the company's sector peers did*.
2. **News.** How negative the company's recent headlines are, when there are any.

These five signals are weighted with **AHP** (Analytic Hierarchy Process) and combined with **TOPSIS**. The score is stored every trading day, so each company's risk can be tracked over time.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-GitHub%20Pages-2f81f7?style=for-the-badge&logo=github)](https://se23uari120.github.io/brand-risk-index/)
[![Source Code](https://img.shields.io/badge/Repository-GitHub-161b22?style=for-the-badge&logo=github)](https://github.com/se23uari120/brand-risk-index)

> Not investment advice. This is a monitoring tool for brand and reputation risk.

---

## Contents

- [What you see in the dashboard](#what-you-see-in-the-dashboard)
- [How the score works](#how-the-score-works)
  - [Step 1: Collect data](#step-1-collect-data)
  - [Step 2: The five signals](#step-2-the-five-signals)
  - [Step 3: Weighting with AHP](#step-3-weighting-with-ahp)
  - [Step 4: Combining with TOPSIS](#step-4-combining-with-topsis)
  - [Step 5: Risk levels](#step-5-risk-levels)
- [Daily tracking](#daily-tracking)
- [Run it yourself](#run-it-yourself)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [REST API (optional)](#rest-api-optional)
- [Data sources and limitations](#data-sources-and-limitations)

---

## What you see in the dashboard

| Tab | What it shows |
|---|---|
| **Overview** | Counts of High / Moderate risk companies, the highest-risk companies with a one-line reason each, the biggest risers this week, the companies with the most negative news, and average risk by sector. |
| **All companies** | A searchable, sortable table of every company: score, level, 1-week change, company-specific share move, news count and a 30-day trend line. |
| **Company panel** (click any company) | The score in plain English ("*The shares did 13.4% worse than expected this week, after allowing for the NIFTY 50 and its sector peers…*"), the five signals with their evidence, the risk-score history, price vs NIFTY 50, the company-specific performance line, the recent headlines with their sentiment, and the full TOPSIS calculation for that company. |
| **Compare** | Up to four companies side by side: score trends, the five signals and the key numbers. |
| **How it works** | The whole method explained, using today's real numbers. The AHP weights are recomputed in your browser from the matrix, and a TOPSIS worked example is shown for any company you pick. |

It works on phones, and in light or dark mode.

---

## How the score works

When something damages a company's reputation (a recall, a regulator's probe, a fatal accident, a guidance cut), it shows up in two places. **Investors sell the shares more than the market explains**, and **the press writes negative stories**. The monitor measures both, and **removes market-wide and sector-wide moves first**, because a falling sector is not a problem with one brand.

```
 NSE prices (Yahoo Finance) ──► stock signals ──► C1 Market reaction ─┐
                                                  C2 Trading stress   │
                                                  C3 Lingering damage ├─► AHP weights ─► TOPSIS ─► score 0–100 ─► level
 Google News headlines ──► relevance filter ──►   C4 News tone        │                                 │
                           ──► sentiment          C5 Negative coverage┘                                 ▼
                                                                                         daily history (tracking)
```

### Step 1: Collect data

**Prices.** For every company, the pipeline downloads one year of daily split- and dividend-adjusted closes and volumes for `SYMBOL.NS`, plus the NIFTY 50 index `^NSEI`, from Yahoo Finance's public chart data. Only `requests` is needed, with no extra finance library.

**News.** For every company, it fetches about 50 days of headlines from a Google News RSS search, then keeps only the relevant ones:

- The headline must name the company, using its name variants (for example "HDFC Bank", or "SBI" matched case-sensitively).
- It must not name a similarly-named company (for example "SBI Life", "L&T Finance" or "Kotak Mahindra" for M&M).
- Generic market wrap-ups ("Sensex, Nifty fall; top losers…") are dropped. They only repeat price moves the stock signals already use.
- Duplicate syndicated copies are collapsed.

Each kept headline gets a **sentiment score from −1 to +1**:

- **FinBERT** (`ProsusAI/finbert`, a BERT model trained on financial news), used when `torch` and `transformers` are installed. The score is P(positive) − P(negative).
- **Finance word list** (fallback), a transparent lexicon of weighted terms such as *probe, penalty, recall, downgrade, fatal accident* versus *order win, upgrade, record profit*. The score is (P − N) / (P + N + 1.5).

A headline is labelled *negative* at ≤ −0.15 and *positive* at ≥ +0.15. The dashboard always says which engine produced the data.

### Step 2: The five signals

Each signal answers one plain question and is converted to **risk points from 0 to 100**.

**The expected-return model (used by C1 and C3).** For each stock, over the 120 trading days that end 20 days before the scored day:

```
expected return  = β_m · r_NIFTY  +  β_s · (r_peers − r_NIFTY)
abnormal return  AR = actual return − expected return        ← the company-specific part
```

`r_peers` is the average return of the company's sector peers in the watchlist, with the company itself excluded. It is used when the sector has at least 3 tracked companies; otherwise β_s = 0. Both betas are shrunk toward 1 (`β' = 0.67·β + 0.33`) for stability. σ is the stock's normal daily abnormal-return noise. So if every IT stock falls 5% on a sector-wide worry, Infosys's abnormal return is about zero.

| # | Signal | Question | Formula → risk points | Weight |
|---|---|---|---|---|
| C1 | **Market reaction** | Did the shares fall more than the market and sector explain? | z₅ = CAR₅ / (σ√5), z₂₀ = CAR₂₀ / (σ√20) <br> `C1 = 100 · clip((max(−z₅, −z₂₀) − 1) / 2, 0, 1)` <br> 0 down to −1σ (noise) · 50 at −2σ (~2% chance) · 100 at −3σ | **36.9%** |
| C2 | **Trading stress** | Is it being traded unusually nervously? | vol ratio = σ(last 10 d) / σ(previous 90 d); volume ratio = mean(last 5 d) / median(previous 60 d) <br> `C2 = ½·clip((vol−1)/1.5) + ½·clip((volume−1)/2)`, **× 0.25 if the stock is beating expectations** (likely good news) | **10.9%** |
| C3 | **Lingering damage** | Has company-specific damage built up and stayed? | Running sum of AR over ~3 months (63 days); gap below its best point, in units of σ√63 <br> `C3 = 100 · clip((gap − 1) / 2, 0, 1)`: 0 up to 1σ · 50 at 2σ · 100 at 3σ | **20.6%** |
| C4 | **News tone** | How negative are the last 7 days of headlines? | `C4 = 100 · Σ max(0, −sentiment) / (headlines + 2)`. The two imaginary neutral headlines stop one stray story from spiking the score. **0 if there is no news.** | **20.6%** |
| C5 | **Negative coverage** | How much negative coverage in the last 7 days? | `C5 = 100 · (1 − e^(−negative headlines / 5))`: 1 → 18, 3 → 45, 5 → 63, 10 → 86 | **10.9%** |

Stock behaviour carries **68%** of the weight and news **32%**. With no news, the score rests on stock behaviour alone.

### Step 3: Weighting with AHP

Weights are not guessed. Each pair of signals is compared on Saaty's 1–9 scale (1 = equal, 2 = slightly more important, 3 = moderately more important):

| Row is … × as important as column | C1 | C2 | C3 | C4 | C5 | **Weight** |
|---|---|---|---|---|---|---|
| C1 Market reaction | 1 | 3 | 2 | 2 | 3 | **36.9%** |
| C2 Trading stress | 1/3 | 1 | 1/2 | 1/2 | 1 | **10.9%** |
| C3 Lingering damage | 1/2 | 2 | 1 | 1 | 2 | **20.6%** |
| C4 News tone | 1/2 | 2 | 1 | 1 | 2 | **20.6%** |
| C5 Negative coverage | 1/3 | 1 | 1/2 | 1/2 | 1 | **10.9%** |

The weights are the matrix's **principal eigenvector**. The consistency check gives λmax = 5.0133, CI = 0.0033, RI(5) = 1.12, and **CR = 0.0030 < 0.10**, so the judgements are consistent. Print it yourself with `py -3 backend/run_pipeline.py --eval-ahp`.

### Step 4: Combining with TOPSIS

TOPSIS scores each company by how close it sits to the worst case compared with the safest case:

1. Normalise: `r = points / 100`
2. Weight: `v = w · r`
3. Ideal points: **A⁺ = 0 on every signal** (safest possible); **A⁻ = 100 on every signal** (worst possible)
4. Distances: `D⁺ = √Σ v²` and `D⁻ = √Σ (w − v)²`
5. **Risk score = 100 · D⁺ / (D⁺ + D⁻)**

Why fixed ideal points? Classic TOPSIS uses the best and worst company *of the day*, which forces someone to 100 and someone to 0 even on a calm day. Fixed ideal points make **a score of 40 today mean the same as 40 last month**, which a tracker needs.

TOPSIS also means **one severe signal is not averaged away**. If only Market reaction is at 100, a weighted average gives 37, but TOPSIS gives about 53. With every signal at 50, the score is exactly 50.

### Step 5: Risk levels

| Level | Score | Meaning / what to do |
|---|---|---|
| **High** | 50 – 100 | Strong, company-specific stress. Escalate to communications / IR and respond quickly. |
| **Moderate** | 30 – 50 | Something unusual is happening. Review the headlines and price action; prepare a holding statement. |
| **Low** | 0 – 30 | Normal behaviour. Keep routine monitoring. |

The cut-offs are deliberately strict. On a normal day most NIFTY 50 companies should be Low.

**Example (data as of the 19 Nov 2026 NSE close).** Tata Motors PV scored **70 (High)**. The shares fell 13.4% more than the market and sector explained (−3.8σ), after Jaguar Land Rover cut its outlook and the company reported a quarterly loss, and 25 of 40 headlines that week were negative. Meanwhile TCS fell 4.1% that week, but its sector peers fell 4.5%, so the company-specific move was about zero and it correctly stayed **Low**.

---

## Daily tracking

- **Automatic updates.** `.github/workflows/update-risk-data.yml` runs every weekday at **16:45 IST**, after the 15:30 NSE close. It installs the pipeline with FinBERT (CPU), scores every company, and commits `js/data.js` and `backend/output/*.json`, so the GitHub Pages site updates itself. You can also run it by hand from the *Actions* tab ("Run workflow").
  - In the repo, go to **Settings → Actions → General → Workflow permissions** and choose "Read and write permissions", so the job can commit.
- **Point-in-time scoring.** Each day uses only prices up to that day's close and headlines published up to that day.
- **History.** The first run backfills 30 trading days. After that each run adds the new day, refreshes only the last 5 days (late news, corrected prices) and keeps past days frozen. Up to 400 trading days are kept in `backend/output/history.json`.

---

## Run it yourself

Requires Python 3.10+.

```bash
pip install -r backend/requirements.txt
```

```bash
py -3 backend/run_pipeline.py
```

Then open `index.html` in a browser (double-click it, or run `py -3 -m http.server` and visit http://localhost:8000).

Useful options:

| Command | What it does |
|---|---|
| `py -3 backend/run_pipeline.py` | Full run: download prices and news, score, update history and the dashboard (~2 min) |
| `py -3 backend/run_pipeline.py --offline` | Re-score using the last downloaded data (no network) |
| `py -3 backend/run_pipeline.py --limit 5` | Quick test on the first 5 companies (nothing saved) |
| `py -3 backend/run_pipeline.py --sentiment finbert` | Force FinBERT (`auto` uses it when installed, `lexicon` forces the word list) |
| `py -3 backend/run_pipeline.py --reset-history` | Throw away stored history and backfill 30 days again |
| `py -3 backend/run_pipeline.py --eval-ahp` | Print the AHP matrix, weights and consistency ratio |
| `py -3 backend/run_pipeline.py --test-headline "SEBI probes accounting lapses at XYZ"` | Score any headline |

To use FinBERT locally (~1 GB including the model), install the small CPU build of torch first:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```bash
pip install -r backend/requirements-finbert.txt
```

---

## Configuration

| What | Where |
|---|---|
| Which companies are tracked, their sector, news query, name variants and exclusions | `backend/data/watchlist.json`. Add any NSE symbol here. |
| Windows (estimation, event, volatility, volume, drawdown), news window, level thresholds, history length | `backend/config.py` |
| AHP pairwise judgements | `backend/mcdm/ahp.py` (`DEFAULT_PAIRWISE`) |
| Signal formulas and their explanations (shown in the dashboard) | `backend/engine/criteria.py` |

---

## Project structure

```
fdetection/
├── index.html                    # Dashboard (single page, no build step)
├── css/style.css                 # Light/dark design tokens and layout
├── js/
│   ├── data.js                   # GENERATED by the pipeline: scores, signals, history, prices, headlines
│   ├── util.js                   # Formatting, level badges, plain-English explanations
│   ├── charts.js                 # Themed Chart.js wrappers (crosshair, risk zones, end labels)
│   ├── overview.js               # Overview tab
│   ├── companies.js              # All-companies table
│   ├── detail.js                 # Company panel (reasons, signals, charts, headlines, TOPSIS working)
│   ├── compare.js                # Compare tab
│   ├── method.js                 # "How it works" tab with live AHP/TOPSIS examples
│   └── app.js                    # Routing (#company/TMPV deep links), theme, bootstrap
├── .github/workflows/
│   └── update-risk-data.yml      # Daily automated update after NSE close
└── backend/
    ├── run_pipeline.py           # Command-line runner
    ├── config.py                 # All tunable settings
    ├── api.py                    # Optional FastAPI server
    ├── requirements*.txt         # core / FinBERT / API dependencies
    ├── data/watchlist.json       # NSE companies tracked (NIFTY 50)
    ├── market/
    │   ├── nse_prices.py         # Yahoo Finance download + cache
    │   └── stock_signals.py      # Two-factor model, abnormal returns, z-scores, stress, drawdown
    ├── nlp/
    │   ├── news.py               # Google News RSS + relevance filtering
    │   └── sentiment.py          # FinBERT and finance word-list engines
    ├── mcdm/
    │   ├── ahp.py                # AHP eigenvector weights + consistency ratio
    │   └── topsis.py             # TOPSIS with fixed ideal points
    ├── engine/
    │   ├── criteria.py           # The five signals (formulas + explanations)
    │   └── risk_scorer.py        # Orchestrates everything, writes outputs
    └── output/
        ├── latest.json           # Full results of the last run
        └── history.json          # Daily score history per company (the tracker)
```

---

## REST API (optional)

```bash
pip install -r backend/requirements-api.txt
```

```bash
py -3 backend/api.py
```

The dashboard is then at http://127.0.0.1:8000, with interactive docs at `/docs`.

| Endpoint | Returns |
|---|---|
| `GET /api/summary` | As-of date, sentiment engine, counts per level |
| `GET /api/companies?sector=&level=&q=` | Ranked list |
| `GET /api/companies/{symbol}` | Full record, including signals, history and headlines |
| `GET /api/sectors` | Average score per sector |
| `GET /api/method` | Signal definitions and AHP weights |
| `POST /api/score-headline` | Sentiment of any headline: `{"text": "..."}` |
| `POST /api/refresh` | Re-runs the pipeline now |

---

## Data sources and limitations

- **Prices** come from Yahoo Finance's public chart data. It is unofficial and can occasionally be late or revised. The newest bar is taken from Yahoo's final market quote once the session has closed.
- **Headlines** come from Google News RSS (for personal, non-commercial use). Only headlines are analysed, not full articles.
- **The word-list sentiment engine is crude.** It can misread headlines; for example, "court sets aside sanction to prosecute" contains "scam" in a positive story. FinBERT is better, and the daily job uses it.
- **A stock fall is not always a brand problem.** Results, guidance or analyst calls also move prices. Each company's headlines are shown so you can judge the cause.
- **A Low score does not mean no reputational issue.** If the market shrugs off bad news, the stock signals stay quiet. The Overview's "Most negative news" list catches those cases (for example, a fatal plant accident with no share-price reaction).
- **Sector peers come from the watchlist.** With the NIFTY 50, some sectors have only a few members, and sectors with fewer than 3 are compared with the NIFTY 50 only.
