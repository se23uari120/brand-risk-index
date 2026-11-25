"""
market/stock_signals.py
=======================
Turns raw daily prices into "stock effect" signals: how unusually a company's
shares are behaving *after removing what the market and its sector did*.

Expected-return model (two factors, estimated per stock)
-------------------------------------------------------
    expected r_i = β_m · r_NIFTY  +  β_s · (r_peers − r_NIFTY)

    r_peers  = average daily log return of the company's sector peers in the
               watchlist (the company itself excluded). Used when the sector
               has at least 3 members; otherwise β_s = 0 (market only).
    β_m, β_s = least-squares estimates over the 120 trading days that end
               20 days before the scored day, shrunk toward 1
               (β' = 0.67·β + 0.33) so one odd month cannot distort them.

    abnormal return  AR = r_i − expected r_i     (the company-specific part)

So if every IT stock falls 5% on a sector-wide worry, Infosys' abnormal
return is ~0: that is not damage to *its* brand.

Signals for each day t (point-in-time: only data up to t is used)
------------------------------------------------------------------
car5, car20   Σ AR over the last 5 / 20 trading days
z5, z20       CAR / (σ · √n), σ = the stock's normal daily AR noise.
              z = −2 → a drop that size happens by chance only ~2% of the time
vol_ratio     volatility of the last 10 days ÷ the 90 days before
volume_ratio  mean volume of the last 5 days ÷ median of the 60 days before
dd_sigma      drawdown of the cumulative-AR line from its 3-month best,
              in units of σ·√63 (≈0.8 is typical, >2 happens ~5% of the time)
"""

import math

import numpy as np
import pandas as pd

from config import (DRAWDOWN_DAYS, ESTIMATION_DAYS, EVENT_LONG, EVENT_SHORT,
                    VOL_BASE, VOL_SHORT, VOLUME_BASE, VOLUME_SHORT)

BETA_SHRINK = 0.67
MIN_PEERS = 2                     # sector needs ≥ 2 *other* members to form a peer factor
MIN_HISTORY = 1 + ESTIMATION_DAYS + EVENT_LONG
# A recent listing or demerger (e.g. Vedanta Aluminium, June 2026) is scored once it
# has MIN_ESTIMATION days to learn from; its windows shrink to the history available.
MIN_ESTIMATION = 60
MIN_SHORT_HISTORY = 1 + MIN_ESTIMATION + EVENT_LONG


def log_returns(adj: pd.Series) -> pd.Series:
    return np.log(adj).diff()


def peer_returns(returns: dict[str, pd.Series], sectors: dict[str, str]) -> dict[str, pd.Series | None]:
    """Equal-weighted peer log return per company (company itself excluded)."""
    panel = pd.DataFrame(returns)
    out = {}
    for sym, sec in sectors.items():
        peers = [s for s, ss in sectors.items() if ss == sec and s != sym and s in panel]
        out[sym] = panel[peers].mean(axis=1, skipna=True) if len(peers) >= MIN_PEERS else None
    return out


def compute_stock_signals(stock: pd.DataFrame, bench: pd.DataFrame,
                          peer: pd.Series | None, n_days: int, path_days: int):
    """
    stock: DataFrame[close, adj, volume]   bench: DataFrame[adj] (NIFTY)
    peer : daily peer log returns (or None)
    Returns (signals DataFrame indexed by date, company-specific performance
    path for the last `path_days` days as a Series of cumulative AR in %).
    """
    df = stock[["close", "adj", "volume"]].join(bench[["adj"]].rename(columns={"adj": "mkt"}), how="inner")
    r = log_returns(df["adj"]).to_numpy()
    rm = log_returns(df["mkt"]).to_numpy()
    rp = peer.reindex(df.index).to_numpy() if peer is not None else np.full(len(df), np.nan)
    rs = np.where(np.isnan(rp), 0.0, rp - rm)            # sector move beyond the market
    has_peer = peer is not None
    p, m, v = df["adj"].to_numpy(), df["mkt"].to_numpy(), df["volume"].to_numpy(float)

    rows, path = [], None
    start = max(MIN_SHORT_HISTORY, len(df) - n_days)
    for k in range(start, len(df)):
        # 1. Fit the expected-return model on the estimation window (index 0 has no return)
        est = slice(max(1, k - EVENT_LONG - ESTIMATION_DAYS + 1), k - EVENT_LONG + 1)
        X = np.column_stack([rm[est], rs[est]]) if has_peer else rm[est][:, None]
        y = r[est]
        ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        coef = np.linalg.lstsq(X[ok], y[ok], rcond=None)[0]
        coef = BETA_SHRINK * coef + (1 - BETA_SHRINK)
        beta_m = float(coef[0])
        beta_s = float(coef[1]) if has_peer else 0.0

        ar = r - beta_m * rm - beta_s * rs                # abnormal (company-specific) returns
        sigma = float(np.nanstd(ar[est], ddof=1)) or 1e-6

        # 2. How unusual is the recent abnormal return?
        car5 = float(np.nansum(ar[k - EVENT_SHORT + 1:k + 1]))
        car20 = float(np.nansum(ar[k - EVENT_LONG + 1:k + 1]))
        z5 = car5 / (sigma * math.sqrt(EVENT_SHORT))
        z20 = car20 / (sigma * math.sqrt(EVENT_LONG))

        # 3. Trading stress
        recent_vol = np.nanstd(r[k - VOL_SHORT + 1:k + 1], ddof=1)
        base_vol = np.nanstd(r[max(1, k - VOL_SHORT - VOL_BASE + 1):k - VOL_SHORT + 1], ddof=1)
        vol_ratio = float(recent_vol / base_vol) if base_vol > 0 else 1.0
        recent_volu = np.nanmean(v[k - VOLUME_SHORT + 1:k + 1])
        base_volu = np.nanmedian(v[max(0, k - VOLUME_SHORT - VOLUME_BASE + 1):k - VOLUME_SHORT + 1])
        volume_ratio = float(recent_volu / base_volu) if base_volu > 0 else 1.0

        # 4. Lingering damage: drawdown of the cumulative-AR line over ~3 months
        cum = np.concatenate([[0.0], np.nancumsum(ar[max(1, k - DRAWDOWN_DAYS + 1):k + 1])])
        dd = float(cum.max() - cum[-1])
        dd_sigma = dd / (sigma * math.sqrt(DRAWDOWN_DAYS))

        rows.append({
            "date": df.index[k], "close": float(df["close"].iloc[k]),
            "beta": beta_m, "beta_sector": beta_s, "sigma": sigma, "est_days": est.stop - est.start,
            "car5": car5, "car20": car20, "z5": z5, "z20": z20,
            "excess5": math.exp(car5) - 1, "excess20": math.exp(car20) - 1,
            "ret5": p[k] / p[k - 5] - 1, "ret20": p[k] / p[k - 20] - 1,
            "idx_ret5": m[k] / m[k - 5] - 1, "idx_ret20": m[k] / m[k - 20] - 1,
            "peer_ret5": float(math.exp(np.nansum(rp[k - 4:k + 1])) - 1) if has_peer else None,
            "vol_ratio": vol_ratio, "volume_ratio": volume_ratio,
            "abn_drawdown": 1 - math.exp(-dd), "dd_sigma": dd_sigma,
        })
        if k == len(df) - 1:     # company-specific performance line for the chart
            seg = np.nan_to_num(ar[-path_days:])
            path = pd.Series((np.exp(np.cumsum(seg)) - 1) * 100, index=df.index[-path_days:])

    return pd.DataFrame(rows).set_index("date"), path
