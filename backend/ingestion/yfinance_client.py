"""MSFT spot price and 5-year monthly beta vs SPY.

Primary source: Yahoo Finance chart API (v8), same data the yfinance library uses.

Yahoo often returns HTTP 429 from cloud/Docker/datacenter IPs. If ``ALPHA_VANTAGE_API_KEY``
is set in the environment, we fall back to Alpha Vantage ``TIME_SERIES_MONTHLY_ADJUSTED``
(free tier: https://www.alphavantage.co/support/#api-key).
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

YAHOO_CHART_HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }


def _monthly_adj_close_series(symbol: str) -> pd.Series:
    last_err: Exception | None = None
    for host in YAHOO_CHART_HOSTS:
        url = host.format(symbol=symbol)
        for attempt in range(4):
            r = requests.get(
                url,
                params={"range": "5y", "interval": "1mo"},
                headers=_browser_headers(),
                timeout=90,
            )
            if r.status_code in (429, 503):
                time.sleep(1.5 * (2**attempt))
                continue
            if not r.ok:
                last_err = requests.HTTPError(f"{r.status_code} for {url}", response=r)
                break
            payload = r.json()
            block = payload.get("chart", {}).get("result")
            if not block:
                raise ValueError(f"Yahoo chart returned no result for {symbol}")
            data = block[0]
            ts = data.get("timestamp") or []
            adj = (data.get("indicators") or {}).get("adjclose", [{}])[0].get("adjclose")
            if not ts or not adj or len(ts) != len(adj):
                raise ValueError(f"Yahoo chart series incomplete for {symbol}")
            idx = pd.DatetimeIndex([datetime.fromtimestamp(t, tz=timezone.utc) for t in ts])
            s = pd.Series([float(x) for x in adj], index=idx, dtype="float64")
            return s.dropna()
        continue
    if last_err:
        raise last_err
    raise ValueError(f"Could not load Yahoo chart for {symbol}")


def _monthly_adj_close_series_alphavantage(symbol: str) -> pd.Series:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        raise ValueError("ALPHA_VANTAGE_API_KEY is not set")
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_MONTHLY_ADJUSTED",
            "symbol": symbol,
            "apikey": key,
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
    av_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    price_source = "yahoo_chart"
    try:
        hist = _monthly_adj_close_series("MSFT")
        time.sleep(0.4)
        spy = _monthly_adj_close_series("SPY")
    except Exception as yahoo_err:
        if not av_key:
            raise ValueError(
                "Could not load prices from Yahoo Finance (HTTP 429/blocks are common from Docker "
                "or datacenter IPs). Add a free ALPHA_VANTAGE_API_KEY to .env for monthly adjusted "
                "MSFT/SPY history, or run ingestion from a network where Yahoo succeeds."
            ) from yahoo_err
        hist = _monthly_adj_close_series_alphavantage("MSFT")
        time.sleep(15)
        spy = _monthly_adj_close_series_alphavantage("SPY")
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
