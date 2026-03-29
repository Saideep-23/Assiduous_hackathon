"""MSFT spot price and 5-year monthly beta vs SPY.

Monthly adjusted closes come from Alpha Vantage ``TIME_SERIES_MONTHLY_ADJUSTED``.
``ALPHA_VANTAGE_API_KEY`` must be set in the environment (see ``.env.example``).
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

from database.connection import get_connection


def _monthly_adj_close_series(symbol: str, api_key: str) -> pd.Series:
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_MONTHLY_ADJUSTED",
            "symbol": symbol,
            "apikey": api_key,
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    series = data.get("Monthly Adjusted Time Series")
    if not series:
        hint = data.get("Note") or data.get("Information") or str(data)[:400]
        raise ValueError(f"Alpha Vantage did not return monthly series for {symbol}: {hint}")
    rows: list[tuple[pd.Timestamp, float]] = []
    for date_str in sorted(series.keys()):
        adj = series[date_str].get("5. adjusted close")
        if adj is None:
            continue
        rows.append((pd.Timestamp(date_str, tz="UTC"), float(adj)))
    if len(rows) < 12:
        raise ValueError(f"Alpha Vantage series too short for {symbol}")
    idx = pd.DatetimeIndex([d for d, _ in rows])
    vals = [v for _, v in rows]
    s = pd.Series(vals, index=idx, dtype="float64")
    cutoff = s.index.max() - pd.DateOffset(years=5)
    s = s[s.index >= cutoff]
    return s.dropna()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_stale(pulled_at: str, observation_ts: datetime) -> bool:
    try:
        pt = datetime.fromisoformat(pulled_at.replace("Z", "+00:00"))
        return (pt - observation_ts.replace(tzinfo=timezone.utc)).total_seconds() > 24 * 3600
    except Exception:
        return True


def fetch_price_and_beta() -> dict[str, Any]:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "ALPHA_VANTAGE_API_KEY is not set. Add it to your .env file (see .env.example)."
        )
    hist = _monthly_adj_close_series("MSFT", key)
    time.sleep(15)
    spy = _monthly_adj_close_series("SPY", key)
    price_source = "alphavantage_monthly_adjusted"

    if hist.empty or spy.empty:
        raise ValueError("MSFT or SPY monthly history is empty — cannot compute spot price or beta")

    spot_price = float(hist.iloc[-1])
    spot_ts = hist.index[-1].to_pydatetime()
    if spot_ts.tzinfo is None:
        spot_ts = spot_ts.replace(tzinfo=timezone.utc)

    if not math.isfinite(spot_price) or spot_price <= 0:
        raise ValueError("MSFT spot price is missing or invalid")

    aligned = hist.align(spy, join="inner")
    m_ret = np.log(aligned[0] / aligned[0].shift(1)).dropna()
    s_ret = np.log(aligned[1] / aligned[1].shift(1)).dropna()
    common = m_ret.index.intersection(s_ret.index)
    m_ret = m_ret.loc[common]
    s_ret = s_ret.loc[common]
    if len(m_ret) < 24:
        raise ValueError(
            f"Need at least 24 aligned monthly return pairs for beta; got {len(m_ret)}"
        )
    cov = np.cov(m_ret, s_ret)[0, 1]
    var = np.var(s_ret)
    if var <= 0:
        raise ValueError("SPY return variance is zero — cannot compute beta")
    beta = float(cov / var)
    if not math.isfinite(beta):
        raise ValueError("Beta is NaN or infinite — check MSFT/SPY alignment")

    return {
        "spot_price": spot_price,
        "spot_ts": spot_ts,
        "beta_5y_monthly": beta,
        "beta_note": (
            "Beta from 5-year monthly log returns of MSFT vs SPY (aligned months); "
            f"prices from {price_source}."
        ),
    }


def store_market_data(payload: dict[str, Any]) -> None:
    pulled_at = _now_iso()
    stale_px = _is_stale(pulled_at, payload["spot_ts"])
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO market_data (ticker, metric_name, value, pulled_at, is_stale, observation_date)
            VALUES ('MSFT', 'spot_price', ?, ?, ?, ?)
            ON CONFLICT(ticker, metric_name) DO UPDATE SET
              value=excluded.value, pulled_at=excluded.pulled_at, is_stale=excluded.is_stale, observation_date=excluded.observation_date
            """,
            (
                payload["spot_price"],
                pulled_at,
                1 if stale_px else 0,
                payload["spot_ts"].date().isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO market_data (ticker, metric_name, value, pulled_at, is_stale, observation_date)
            VALUES ('MSFT', 'beta_5y_monthly', ?, ?, ?, ?)
            ON CONFLICT(ticker, metric_name) DO UPDATE SET
              value=excluded.value, pulled_at=excluded.pulled_at, is_stale=excluded.is_stale, observation_date=excluded.observation_date
            """,
            (
                payload["beta_5y_monthly"],
                pulled_at,
                1 if stale_px else 0,
                payload["spot_ts"].date().isoformat(),
            ),
        )


async def run_yfinance_ingestion() -> dict[str, Any]:
    p = fetch_price_and_beta()
    store_market_data(p)
    return p
