"""
market/nse_prices.py
====================
Downloads daily NSE price history (split/dividend-adjusted close + volume)
from Yahoo Finance's public chart endpoint.

* NSE symbols are queried as  <SYMBOL>.NS   (e.g. RELIANCE.NS, M&M.NS)
* The benchmark is the NIFTY 50 index  ^NSEI
* Every successful download is cached under backend/cache/prices/, so the
  pipeline can be re-run offline (`--offline`) with the last downloaded data.

Only `requests` + `pandas` are needed (no yfinance dependency).
"""

import json
import logging
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from config import CACHE_DIR, EXCHANGE_SUFFIX, PRICE_RANGE

logger = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
PRICE_CACHE = CACHE_DIR / "prices"
PRICE_CACHE.mkdir(parents=True, exist_ok=True)

IST = timezone(timedelta(hours=5, minutes=30))
NSE_CLOSE_IST = (15, 40)   # bars for "today" before this time are still forming

_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) brand-risk-monitor"


def yahoo_ticker(symbol: str) -> str:
    """NSE symbol → Yahoo ticker. Index symbols (^NSEI) pass through unchanged."""
    return symbol if symbol.startswith("^") else f"{symbol}{EXCHANGE_SUFFIX}"


def _cache_path(symbol: str, tag: str = ""):
    safe = symbol.replace("^", "IDX_").replace("&", "_and_")
    return PRICE_CACHE / f"{safe}{tag}.json"


def _download(symbol: str, period: tuple[date, date] | None = None, retries: int = 3) -> dict:
    ticker = urllib.parse.quote(yahoo_ticker(symbol))
    params = {"interval": "1d", "events": "div,splits"}
    if period:
        params["period1"] = int(datetime(period[0].year, period[0].month, period[0].day, tzinfo=timezone.utc).timestamp())
        params["period2"] = int(datetime(period[1].year, period[1].month, period[1].day, tzinfo=timezone.utc).timestamp()) + 86400
    else:
        params["range"] = PRICE_RANGE
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = _session.get(CHART_URL.format(ticker=ticker), params=params, timeout=20)
            r.raise_for_status()
            payload = r.json()
            result = (payload.get("chart") or {}).get("result")
            if not result:
                raise ValueError(f"empty chart result: {payload.get('chart', {}).get('error')}")
            return result[0]
        except Exception as exc:          # network hiccup / rate limit → back off and retry
            last_err = exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"Yahoo Finance download failed for {symbol}: {last_err}")


def _to_frame(result: dict) -> pd.DataFrame:
    """Convert a Yahoo chart payload into a tidy daily DataFrame indexed by IST date."""
    ts = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    offset = int(result.get("meta", {}).get("gmtoffset", 19800))

    meta = result.get("meta", {})
    dates = [datetime.fromtimestamp(t + offset, tz=timezone.utc).date() for t in ts]
    closes = list(quote.get("close") or [None] * len(ts))
    adjs = list(adj) if adj else list(closes)
    vols = list(quote.get("volume") or [0] * len(ts))

    # Yahoo often leaves the newest bar empty and reports the final price only in
    # meta.regularMarketPrice. Fill it in when that quote belongs to the same day.
    rmt, rmp = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if dates and closes[-1] is None and rmt and rmp:
        if datetime.fromtimestamp(rmt + offset, tz=timezone.utc).date() == dates[-1]:
            closes[-1], adjs[-1] = float(rmp), None          # adj rebuilt from factor below
            if not vols[-1]:
                vols[-1] = meta.get("regularMarketVolume") or 0

    df = pd.DataFrame({"date": dates, "close": closes, "adj": adjs, "volume": vols})
    df[["close", "adj", "volume"]] = df[["close", "adj", "volume"]].astype(float)
    # Yahoo sometimes leaves adjclose empty for the newest bar(s): carry the last
    # known adjustment factor forward instead of dropping the day.
    df["adj"] = df["close"] * (df["adj"] / df["close"]).ffill().fillna(1.0)
    df = df.dropna(subset=["close"])
    df["volume"] = df["volume"].fillna(0).astype(float)
    df = df.drop_duplicates("date", keep="last").set_index("date").sort_index()
    df.index = pd.to_datetime(df.index)

    # Drop today's bar if the NSE session has not closed yet (it is still moving).
    now_ist = datetime.now(tz=IST)
    if len(df) and df.index[-1].date() == now_ist.date() and \
            (now_ist.hour, now_ist.minute) < NSE_CLOSE_IST:
        df = df.iloc[:-1]
    return df


def get_prices(symbol: str, offline: bool = False,
               period: tuple[date, date] | None = None) -> tuple[pd.DataFrame, dict]:
    """
    Return (daily DataFrame[close, adj, volume], meta) for one NSE symbol.
    period=(start, end) downloads that date range instead of the last year
    (used by the back-test and past-period search).
    With offline=True the cached download is used instead of the network.
    """
    cache = _cache_path(symbol, f"_{period[0]:%Y%m%d}_{period[1]:%Y%m%d}" if period else "")
    result = None
    if not offline:
        try:
            result = _download(symbol, period)
            cache.write_text(json.dumps(result), encoding="utf-8")
        except Exception as exc:
            logger.warning("%s — falling back to cache", exc)
    if result is None:
        if not cache.exists():
            raise RuntimeError(f"No price data (network failed and no cache) for {symbol}")
        result = json.loads(cache.read_text(encoding="utf-8"))

    meta = result.get("meta", {})
    info = {
        "longName": meta.get("longName") or meta.get("shortName"),
        "currency": meta.get("currency", "INR"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "fiftyTwoWeekHigh": meta.get("fiftyTwoWeekHigh"),
        "fiftyTwoWeekLow": meta.get("fiftyTwoWeekLow"),
    }
    return _to_frame(result), info
