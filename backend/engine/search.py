"""
engine/search.py
================
Company Search: the brand-risk assessment for ANY NSE-listed company,
live or as of a past date — scored exactly like the monitored companies
(engine/assess.py), so the numbers are directly comparable.

Also used by the back-test (engine/backtest.py) to score a company as of an
incident date.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config import BACKTEST_MAX_PEERS, BENCHMARK_SYMBOL, CHART_DAYS
from engine.assess import IST, assess_company, end_of_day, score_headlines
from market.nse_prices import get_prices
from market.stock_signals import log_returns
from market.symbols import load_watchlist, resolve
from mcdm.ahp import AHP
from nlp.feeds import fetch_outlet_feeds
from nlp.news import fetch_company_news

logger = logging.getLogger(__name__)
HISTORY_DAYS = 30


def _prices(symbol: str, period, prefer_cache: bool):
    """Live mode reuses the pipeline's cached download when there is one."""
    if prefer_cache and period is None:
        try:
            return get_prices(symbol, offline=True)
        except Exception:
            pass
    return get_prices(symbol, period=period)


def _peer_returns(symbol: str, sector: str, period, cut: pd.Timestamp, live: bool):
    peers = [c["symbol"] for c in load_watchlist()["companies"] if c["sector"] == sector and c["symbol"] != symbol]
    rets = []
    for p in peers[:BACKTEST_MAX_PEERS]:
        try:
            df, _ = _prices(p, period, live)
            rets.append(log_returns(df["adj"][df.index <= cut]).rename(p))
        except Exception as exc:
            logger.info("peer %s unavailable: %s", p, exc)
    if len(rets) < 2:
        return None
    return pd.concat(rets, axis=1).mean(axis=1, skipna=True)


def score_as_of(profile: dict, as_of_day: date, sentiment, weights=None, live: bool = False,
                n_days: int = HISTORY_DAYS, news_days: int = HISTORY_DAYS + 15, bootstrap: bool = True,
                period: tuple[date, date] | None = None):
    """
    Score one company (watchlist-style profile with symbol/name/sector/query/aliases)
    as of `as_of_day`. Returns (record, bench_frame).
    """
    weights = np.asarray(weights if weights is not None else AHP().compute()["weights"])
    if period is None and not live:
        period = (as_of_day - timedelta(days=430), as_of_day)
    cut = pd.Timestamp(as_of_day)
    prices, info = _prices(profile["symbol"], period, live)
    bench, _ = _prices(BENCHMARK_SYMBOL, period, live)
    prices, bench = prices[prices.index <= cut], bench[bench.index <= cut]
    peer = _peer_returns(profile["symbol"], profile.get("sector"), period, cut, live)

    if live:
        articles, stats = fetch_company_news(profile, outlet_pool=fetch_outlet_feeds(offline=True))
        now = datetime.now(tz=timezone.utc)
    else:
        articles, stats = fetch_company_news(profile, window=(as_of_day - timedelta(days=news_days), as_of_day))
        now = end_of_day(as_of_day)
    score_headlines(articles, sentiment)
    rec = assess_company(profile, prices, info, peer, bench, articles, weights, as_of_day, now, n_days, bootstrap)
    rec["news"].update({k: stats[k] for k in ("fetched", "kept", "rejected", "providers")})
    return rec, bench


def search_company(query: str, sentiment, date_to: date | None = None) -> dict:
    """
    Full search result for the dashboard. date_to=None → live (today);
    otherwise the assessment as of that past day.
    """
    profile = resolve(query)
    if not profile:
        raise LookupError(f"No NSE-listed company found for '{query}'")
    today = datetime.now(tz=IST).date()
    live = date_to is None or date_to >= today
    rec, bench = score_as_of(profile, today if live else date_to, sentiment, live=live)

    daily = rec.pop("_daily")
    rec.pop("_window", None)
    hist_dates = sorted(daily)
    closes, path = rec.pop("_closes"), rec.pop("_path")
    chart_dates = bench.index[-CHART_DAYS:]
    rec["history"] = [round(daily[d], 1) for d in hist_dates]
    past = rec["history"][:-1]
    rec["change5d"] = round(rec["score"] - past[-5], 1) if len(past) >= 5 else None
    rec["closes"] = [None if pd.isna(closes.get(d)) else round(float(closes.get(d)), 2) for d in chart_dates]
    rec["specific"] = [None if path is None or pd.isna(path.get(d)) else round(float(path.get(d)), 2) for d in chart_dates]
    rec["rank"] = None
    return {
        "company": rec,
        "context": {"historyDates": hist_dates, "chartDates": [d.date().isoformat() for d in chart_dates],
                    "benchmarkCloses": [round(float(x), 2) for x in bench["close"].iloc[-CHART_DAYS:]]},
        "live": live,
        "onWatchlist": bool(profile.get("onWatchlist")),
        "profile": {k: profile.get(k) for k in ("symbol", "name", "sector", "query", "aliases", "exclude", "legalName")},
    }
