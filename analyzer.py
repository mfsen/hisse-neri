"""Teknik analiz indikatörlerini hesaplar."""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TechnicalIndicators:
    symbol: str
    name: str
    last_price: float
    # Trend
    sma20: float = 0.0
    sma50: float = 0.0
    sma200: float = 0.0
    ema12: float = 0.0
    ema26: float = 0.0
    # Momentum
    rsi14: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    # Volatilite
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_pct: float = 0.5          # 0=lower 0.5=middle 1=upper
    atr14: float = 0.0
    # Hacim
    volume_ratio: float = 1.0    # cari / 20g ort
    avg_turnover_tl: float = 0.0 # 20g ort. TL işlem hacmi (likidite)
    illiquid: bool = False       # likidite eşiğinin altında
    # Değişimler
    change_1d: float = 0.0
    change_5d: float = 0.0
    change_20d: float = 0.0
    change_60d: float = 0.0
    # Ek
    above_sma200: bool = False
    above_sma50: bool = False
    trend_up: bool = False       # fiyat>SMA50 ve SMA20>SMA50 (sağlıklı yukarı yapı)
    golden_cross: bool = False   # sma50 > sma200 & sma20 > sma50
    death_cross: bool = False
    macd_bullish: bool = False
    macd_hist_rising: bool = False   # histogram dünden iyi (momentum dönüyor)
    rsi_oversold: bool = False
    rsi_overbought: bool = False
    high_volume: bool = False
    near_lower_bb: bool = False
    reclaimed_lower_bb: bool = False # dün alt bandın altında, bugün üstünde (dönüş teyidi)
    stoch_cross_up: bool = False     # %K, %D'yi aşağıdan yukarı kesti
    falling_knife: bool = False      # sert düşüş + negatif momentum + SMA20 altı (teyitsiz dip)
    # 52-hafta
    week52_high: float = 0.0
    week52_low: float = 0.0
    dist_from_52w_low: float = 0.0
    # Stochastic
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    stoch_oversold: bool = False
    # 20 günlük yapı (stop/hedef için)
    high_20d: float = 0.0
    low_20d: float = 0.0
    signals: list = field(default_factory=list)


# Likidite eşiği: 20 günlük ortalama TL işlem hacmi bunun altındaysa "ince" sayılır.
MIN_TURNOVER_TL = 20_000_000  # ~20M TL/gün


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder'in orijinal RSI'ı (RMA yumuşatması). Platformlarla (TradingView/Matriks) uyumlu."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing = alpha = 1/period EMA
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    # Kayıp yokken (sadece yükseliş) RSI = 100; 50'ye düşürme bug'ı giderildi
    rsi = rsi.where(avg_loss != 0, 100.0)
    return rsi


def _atr(high, low, close, period=14):
    """Wilder ATR (RMA yumuşatması) — basit rolling.mean yerine."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _stochastic(high, low, close, k_period=14, d_period=3):
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    denom = (highest - lowest).replace(0, np.nan)
    k = 100 * (close - lowest) / denom
    d = k.rolling(d_period).mean()
    return k, d


def compute(df: pd.DataFrame, symbol: str, name: str) -> Optional[TechnicalIndicators]:
    """Bir hissenin DataFrame'inden TechnicalIndicators hesaplar."""
    if df is None or len(df) < 60:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)

    ind = TechnicalIndicators(
        symbol=symbol,
        name=name,
        last_price=float(close.iloc[-1]),
    )

    # ---- Hareketli ortalamalar ----
    ind.sma20 = float(close.rolling(20).mean().iloc[-1])
    ind.sma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else ind.sma20
    ind.sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else ind.sma50
    ind.ema12 = float(_ema(close, 12).iloc[-1])
    ind.ema26 = float(_ema(close, 26).iloc[-1])

    # ---- RSI ----
    rsi_series = _rsi(close)
    ind.rsi14 = float(rsi_series.iloc[-1]) if not np.isnan(rsi_series.iloc[-1]) else 50.0

    # ---- MACD ----
    macd_line = _ema(close, 12) - _ema(close, 26)
    signal_line = _ema(macd_line, 9)
    ind.macd = float(macd_line.iloc[-1])
    ind.macd_signal = float(signal_line.iloc[-1])
    ind.macd_hist = ind.macd - ind.macd_signal

    # ---- Bollinger Bands ----
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    ind.bb_upper = float((sma20 + 2 * std20).iloc[-1])
    ind.bb_middle = float(sma20.iloc[-1])
    ind.bb_lower = float((sma20 - 2 * std20).iloc[-1])
    band_range = ind.bb_upper - ind.bb_lower
    if band_range > 0:
        ind.bb_pct = (ind.last_price - ind.bb_lower) / band_range
    else:
        ind.bb_pct = 0.5

    # ---- ATR ----
    atr_series = _atr(high, low, close)
    ind.atr14 = float(atr_series.iloc[-1]) if not np.isnan(atr_series.iloc[-1]) else 0.0

    # ---- Hacim & likidite ----
    vol_avg20 = volume.rolling(20).mean().iloc[-1]
    if vol_avg20 > 0:
        ind.volume_ratio = float(volume.iloc[-1] / vol_avg20)
    # 20 günlük ortalama TL işlem hacmi (fiyat × adet)
    turnover = (close * volume).rolling(20).mean().iloc[-1]
    ind.avg_turnover_tl = float(turnover) if not np.isnan(turnover) else 0.0
    ind.illiquid = ind.avg_turnover_tl < MIN_TURNOVER_TL

    # ---- 20 günlük yapı (stop/hedef seviyeleri) ----
    ind.high_20d = float(high.iloc[-20:].max())
    ind.low_20d = float(low.iloc[-20:].min())

    # ---- Değişimler ----
    def safe_pct(i):
        if len(df) > abs(i) and float(close.iloc[i]) != 0:
            return (float(close.iloc[-1]) - float(close.iloc[i])) / float(close.iloc[i]) * 100
        return 0.0

    ind.change_1d = safe_pct(-2)
    ind.change_5d = safe_pct(-6)
    ind.change_20d = safe_pct(-21)
    ind.change_60d = safe_pct(-61) if len(df) >= 61 else safe_pct(-len(df))

    # ---- 52-hafta ----
    window = min(252, len(df))
    ind.week52_high = float(high.iloc[-window:].max())
    ind.week52_low = float(low.iloc[-window:].min())
    if ind.week52_low > 0:
        ind.dist_from_52w_low = (ind.last_price - ind.week52_low) / ind.week52_low * 100

    # ---- Stochastic ----
    k, d = _stochastic(high, low, close)
    ind.stoch_k = float(k.iloc[-1]) if not np.isnan(k.iloc[-1]) else 50.0
    ind.stoch_d = float(d.iloc[-1]) if not np.isnan(d.iloc[-1]) else 50.0

    # ---- Boolean sinyaller ----
    ind.above_sma200 = ind.last_price > ind.sma200
    ind.above_sma50 = ind.last_price > ind.sma50
    ind.trend_up = ind.last_price > ind.sma50 and ind.sma20 > ind.sma50
    ind.golden_cross = ind.sma50 > ind.sma200 and ind.sma20 > ind.sma50
    ind.death_cross = ind.sma50 < ind.sma200 and ind.sma20 < ind.sma50

    # MACD bullish: MACD histogramı pozitif VE son 3 günde kesişim
    hist_series = macd_line - signal_line
    ind.macd_bullish = (
        ind.macd_hist > 0
        and len(hist_series) >= 3
        and float(hist_series.iloc[-3]) < 0
    )
    # Histogram dünden iyi mi? (negatif bölgede bile olsa momentum dönüyor demektir)
    ind.macd_hist_rising = (
        len(hist_series) >= 2
        and float(hist_series.iloc[-1]) > float(hist_series.iloc[-2])
    )

    ind.rsi_oversold = ind.rsi14 < 35
    ind.rsi_overbought = ind.rsi14 > 70
    ind.high_volume = ind.volume_ratio > 1.5
    ind.near_lower_bb = ind.bb_pct < 0.2
    ind.stoch_oversold = ind.stoch_k < 20 and ind.stoch_d < 20

    # Alt bandı geri alma (dün altında, bugün üstünde) → dönüş teyidi
    if len(close) >= 2 and band_range > 0:
        prev_lower = float((sma20 - 2 * std20).iloc[-2])
        ind.reclaimed_lower_bb = (
            float(close.iloc[-2]) < prev_lower and ind.last_price > ind.bb_lower
        )

    # Stochastic yukarı kesişim (%K, %D'yi aşağıdan keser, hâlâ düşük bölgede)
    if len(k) >= 2 and len(d) >= 2:
        k_prev, d_prev = float(k.iloc[-2]), float(d.iloc[-2])
        if not (np.isnan(k_prev) or np.isnan(d_prev)):
            ind.stoch_cross_up = (
                k_prev <= d_prev and ind.stoch_k > ind.stoch_d and ind.stoch_k < 50
            )

    # Düşen bıçak: teyitsiz dip — sert düşüş + negatif momentum + SMA20 altı + dönüş yok
    ind.falling_knife = (
        ind.change_20d < -10
        and ind.macd_hist < 0
        and not ind.macd_hist_rising
        and ind.last_price < ind.sma20
        and not ind.reclaimed_lower_bb
        and not ind.stoch_cross_up
    )

    # ---- Sinyal listesi ----
    sigs = []
    if ind.rsi_oversold:
        sigs.append(("RSI Aşırı Satım", "bullish"))
    if ind.macd_bullish:
        sigs.append(("MACD Bullish Kesişim", "bullish"))
    if ind.near_lower_bb:
        sigs.append(("Alt Bollinger Bandı", "bullish"))
    if ind.golden_cross:
        sigs.append(("Golden Cross", "bullish"))
    if ind.stoch_oversold:
        sigs.append(("Stochastic Aşırı Satım", "bullish"))
    if ind.above_sma200 and ind.last_price > ind.sma50 > ind.sma20:
        sigs.append(("Kısa Vade Düşüş (SMA)", "bearish"))
    if ind.rsi_overbought:
        sigs.append(("RSI Aşırı Alım", "bearish"))
    if ind.death_cross:
        sigs.append(("Death Cross", "bearish"))
    if ind.high_volume and ind.change_1d > 1:
        sigs.append(("Hacim + Fiyat Artışı", "bullish"))
    ind.signals = sigs

    return ind
