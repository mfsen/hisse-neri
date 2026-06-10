"""Yahoo Finance üzerinden BIST hisse verisi çeker."""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional


def fetch_ticker(symbol: str, period_days: int = 365) -> Optional[pd.DataFrame]:
    """Tek bir hisse için OHLCV verisi döner; başarısızsa None."""
    try:
        end = datetime.today()
        start = end - timedelta(days=period_days)
        df = yf.download(symbol, start=start, end=end,
                         progress=False, auto_adjust=True, timeout=10)
        if df is None or len(df) < 30:
            return None
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        # MultiIndex sütunları düzelt
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        # Gerekli sütunlar
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(set(df.columns)):
            return None
        df = df[list(required)].copy()
        df.dropna(subset=["Close"], inplace=True)
        return df
    except Exception:
        return None


def fetch_all(
    tickers: list[str],
    period_days: int = 365,
    max_workers: int = 12,
    progress_callback=None,
) -> Dict[str, pd.DataFrame]:
    """Birden fazla hisseyi paralel olarak çeker."""
    results: Dict[str, pd.DataFrame] = {}
    done = 0
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {ex.submit(fetch_ticker, t, period_days): t for t in tickers}
        for future in as_completed(future_map):
            ticker = future_map[future]
            df = future.result()
            if df is not None and len(df) >= 30:
                results[ticker] = df
            done += 1
            if progress_callback:
                progress_callback(done, total, ticker)

    return results


def fetch_market_summary() -> dict:
    """BIST 100 endeksi ve USD/TRY için özet bilgi döner."""
    summary = {}
    for sym, label in [("XU100.IS", "BIST 100"), ("USDTRY=X", "USD/TRY")]:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                last = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2])
                chg = (last - prev) / prev * 100
                summary[label] = {"price": last, "change_pct": chg}
        except Exception:
            pass
    return summary
