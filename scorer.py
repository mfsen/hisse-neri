"""Teknik indikatörleri skora çevirir ve hisseleri sıralar."""

from dataclasses import dataclass
from analyzer import TechnicalIndicators
from typing import List


@dataclass
class StockScore:
    symbol: str
    name: str
    score: int             # 0-100
    grade: str             # A+ / A / B / C / D
    strategy: str          # Momentum / Reversal / Trend / Swing
    ind: TechnicalIndicators
    reasons: List[str]
    risks: List[str]
    entry_price: float
    stop_loss: float
    target_price: float
    risk_reward: float


def _grade(score: int) -> str:
    if score >= 80:
        return "A+"
    if score >= 65:
        return "A"
    if score >= 50:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def score_stock(ind: TechnicalIndicators) -> StockScore:
    """
    Felsefe (eski 'her aşırı satımı ödüllendir' yaklaşımı yerine):
      1) TREND REJİMİ (0-30): Yapı yukarı mı? Düşüş trendinde dip-alımı baştan kıs.
      2) DÖNÜŞ TEYİDİ (0-25): Sadece 'ucuz' değil, 'dönüyor mu?' (MACD/Stoch/BB geri alımı)
      3) MOMENTUM (0-20): Hacimli, kontrollü yükseliş.
      4) DEĞER/ESNEKLİK (0-15): Trend içi makul geri çekilme (aşırı satım iyi, ama trend varsa).
      5) CEZALAR: Düşen bıçak, death cross, aşırı alım, likiditesizlik.
    """
    score = 0
    reasons = []
    risks = []

    # ---- 1) TREND REJİMİ (0-30) ----
    if ind.golden_cross:
        score += 18
        reasons.append("Golden Cross: SMA20>SMA50>SMA200 → uzun vadeli yapı güçlü")
    elif ind.trend_up and ind.above_sma200:
        score += 14
        reasons.append("Fiyat SMA50 & SMA200 üzerinde, SMA20>SMA50 → sağlıklı yukarı yapı")
    elif ind.above_sma200:
        score += 8
        reasons.append("Fiyat uzun vadeli SMA200 üzerinde")
    elif ind.death_cross:
        score -= 18
        risks.append("Death Cross: uzun vadeli aşağı trend → dip-alımı riskli")
    else:
        score -= 6
        risks.append("Fiyat SMA200 altında → trend zayıf")

    if ind.macd > 0:  # MACD çizgisi sıfır üstü = orta vade yukarı
        score += 6

    # ---- 2) DÖNÜŞ TEYİDİ (0-25) — 'ucuz' değil, 'dönüyor' mu? ----
    confirmed_turn = False
    if ind.macd_bullish:
        score += 12
        confirmed_turn = True
        reasons.append("MACD bullish kesişim → momentum yukarı dönüyor")
    elif ind.macd_hist > 0:
        score += 6
        reasons.append("MACD histogramı pozitif")
    elif ind.macd_hist_rising:
        score += 4
        confirmed_turn = True
        reasons.append("MACD histogramı toparlanıyor (negatiften daralıyor)")

    if ind.reclaimed_lower_bb:
        score += 7
        confirmed_turn = True
        reasons.append("Alt Bollinger bandı geri alındı → satış tükeniyor")
    if ind.stoch_cross_up:
        score += 6
        confirmed_turn = True
        reasons.append(f"Stochastic yukarı kesişim (K={ind.stoch_k:.0f}>D={ind.stoch_d:.0f})")

    # ---- 3) MOMENTUM (0-20) ----
    if ind.high_volume and ind.change_1d > 0:
        score += 10
        reasons.append(f"Yüksek hacimle yükseliş (hacim ×{ind.volume_ratio:.1f})")
    elif ind.high_volume and ind.change_1d < -2:
        score -= 8
        risks.append("Yüksek hacimle düşüş → satış baskısı")
    elif ind.volume_ratio > 1.2 and ind.change_1d > 0:
        score += 4

    if 0 < ind.change_20d < 25:  # kontrollü orta vade yükseliş
        score += 6
        reasons.append(f"20 günlük kontrollü yükseliş (+{ind.change_20d:.1f}%)")
    elif ind.change_20d > 40:
        score -= 4
        risks.append(f"20 günde aşırı ısınma (+{ind.change_20d:.1f}%) → geri çekilme riski")

    # ---- 4) DEĞER / GERİ ÇEKİLME KALİTESİ (0-15) ----
    # Aşırı satım yalnızca trend yukarıyken (veya dönüş teyitliyken) ödüllendirilir.
    trend_ok = ind.above_sma200 or ind.trend_up
    if ind.rsi14 < 35 and (trend_ok or confirmed_turn):
        score += 12
        reasons.append(f"Trend içi aşırı satım (RSI {ind.rsi14:.1f}) → kaliteli geri çekilme")
    elif 35 <= ind.rsi14 < 45 and trend_ok:
        score += 6
        reasons.append(f"RSI nötr-düşük ({ind.rsi14:.1f}), trend sağlam")
    elif ind.rsi14 < 35 and not (trend_ok or confirmed_turn):
        # ucuz ama teyitsiz ve trend yok → ödül YOK (eski modelin hatası buydu)
        risks.append(f"RSI düşük ({ind.rsi14:.1f}) ama trend zayıf ve dönüş teyidi yok")

    if ind.near_lower_bb and confirmed_turn:
        score += 3
        reasons.append("Alt banda yakın + dönüş teyidi")

    # ---- 5) CEZALAR ----
    if ind.falling_knife:
        score -= 20
        risks.append("DÜŞEN BIÇAK: sert düşüş + negatif momentum + SMA20 altı, dönüş teyidi yok")
    if ind.rsi_overbought:
        score -= 12
        risks.append(f"RSI aşırı alımda ({ind.rsi14:.1f}) → düzeltme riski")
    if ind.bb_pct > 0.95:
        score -= 6
        risks.append("Fiyat üst Bollinger bandında → aşırı gerilmiş")
    if ind.stoch_k > 85:
        score -= 4
    if ind.illiquid:
        score -= 15
        risks.append(f"DÜŞÜK LİKİDİTE (~{ind.avg_turnover_tl/1e6:.0f}M ₺/gün) → işlem zor, kayma yüksek")

    score = max(0, min(100, score))

    # ---- Strateji belirleme ----
    if ind.death_cross or ind.falling_knife:
        strategy = "Kaçın / İzle"
    elif ind.macd_bullish and ind.volume_ratio > 1.3:
        strategy = "Momentum"
    elif (ind.rsi14 < 40 or ind.near_lower_bb) and trend_ok and confirmed_turn:
        strategy = "Trend İçi Dip Alım"
    elif ind.golden_cross or (ind.above_sma200 and ind.macd_hist > 0):
        strategy = "Trend Takibi"
    else:
        strategy = "Swing Trade"

    # ---- Fiyat hedefleri ----
    atr = ind.atr14 if ind.atr14 > 0 else ind.last_price * 0.02
    entry = ind.last_price
    # Stop: ATR bazlı ile 20g dip arasından YAKINI al (sıkı risk yönetimi).
    # max() → fiyata daha yakın değer = daha dar stop = daha iyi R/R.
    atr_stop = entry - 1.5 * atr
    support_stop = ind.low_20d * 0.99 if ind.low_20d > 0 else atr_stop
    stop_loss = round(max(support_stop, atr_stop), 2)
    if stop_loss >= entry:
        stop_loss = round(entry - 1.5 * atr, 2)
    # Hedef: 20g direnç ile 3×ATR yukarısından UZAĞI al.
    target = round(max(ind.high_20d, entry + 3.0 * atr), 2)
    risk = entry - stop_loss
    reward = target - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    return StockScore(
        symbol=ind.symbol,
        name=ind.name,
        score=score,
        grade=_grade(score),
        strategy=strategy,
        ind=ind,
        reasons=reasons,
        risks=risks,
        entry_price=entry,
        stop_loss=stop_loss,
        target_price=target,
        risk_reward=rr,
    )


def rank_stocks(indicators: List[TechnicalIndicators]) -> List[StockScore]:
    scores = [score_stock(i) for i in indicators]
    return sorted(scores, key=lambda s: s.score, reverse=True)
