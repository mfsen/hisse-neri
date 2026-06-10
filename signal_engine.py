"""
Ajan-dostu AL/SAT sinyal motoru (BIST Katilim).

Mimari — SEÇİM (yavaş) ile TETİK (hızlı) ayrılır:
  • scan    : Günde 1 kez, seans KAPANIŞINDAN SONRA çalıştır.
              Günlük göstergelerle adayları seçer, her biri için giriş/stop/hedef
              hesaplar ve watchlist.json'a yazar.
  • monitor : Seans içinde HER ~10 DK çalıştır.
              Canlı fiyatı izleme listesindeki seviyelere karşı kontrol eder,
              durum makinesini (positions.json) günceller ve stdout'a temiz JSON
              olarak AL / SAT / TUT / BEKLE / İPTAL sinyalleri döker.

Ajan entegrasyonu:
  - Ajan `python signal.py monitor` çalıştırır, STDOUT'taki tek JSON nesnesini parse eder.
  - İnsan-okunur loglar STDERR'e gider; stdout SADECE JSON'dur.
  - Pozisyon geçmişi positions.json'da kalıcıdır (zaten-AL-dedim takibi).

Önerilen zamanlama (Europe/Istanbul):
  - 18:20'de bir kez:           python signal.py scan --index 30
  - 10:00–18:05 arası her 10dk: python signal.py monitor --index 30

UYARI: Yatırım tavsiyesi değildir. Yahoo intraday verisi BIST'te ~15dk gecikmeli
olabilir; bedelli/bedelsiz düzeltmeleri kusurlu olabilir. Sinyalleri teyit edin.
"""

import sys
import os
import json
import argparse
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

sys.path.insert(0, os.path.dirname(__file__))

import yfinance as yf
import pandas as pd

import fetcher
import analyzer
import scorer
from bist100 import KATILIM30_TICKERS, KATILIM50_TICKERS, KATILIM100_TICKERS

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(HERE, "watchlist.json")
POSITIONS_FILE = os.path.join(HERE, "positions.json")

INDEX_MAP = {"30": KATILIM30_TICKERS, "50": KATILIM50_TICKERS, "100": KATILIM100_TICKERS}


# --------------------------------------------------------------------------- #
#  Yardımcılar
# --------------------------------------------------------------------------- #
def log(msg):
    """İnsan-okunur log → STDERR (stdout temiz JSON kalsın)."""
    print(msg, file=sys.stderr, flush=True)


def emit(obj):
    """Tek JSON nesnesini STDOUT'a yaz (ajan bunu okur)."""
    print(json.dumps(obj, ensure_ascii=False, indent=2), flush=True)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def is_market_open(force=False):
    """BIST pay piyasası ~10:00–18:10 (Europe/Istanbul), Hafta içi."""
    if force:
        return True
    try:
        from zoneinfo import ZoneInfo
        tr = datetime.now(ZoneInfo("Europe/Istanbul"))
    except Exception:
        tr = datetime.now()  # zoneinfo yoksa yerel saat
    if tr.weekday() >= 5:           # Cmt/Paz
        return False
    minutes = tr.hour * 60 + tr.minute
    return 10 * 60 <= minutes <= 18 * 60 + 10


def fetch_live_prices(symbols):
    """Seans içi son fiyatlar (1dk barların son kapanışı). Eksikler atlanır."""
    prices = {}
    try:
        data = yf.download(symbols, period="1d", interval="1m",
                           progress=False, auto_adjust=True, threads=True, timeout=20)
        if not data.empty:
            close = data["Close"]
            if isinstance(close, pd.Series):  # tek sembol
                col = close.dropna()
                if len(col):
                    prices[symbols[0]] = float(col.iloc[-1])
            else:
                for s in symbols:
                    if s in close.columns:
                        col = close[s].dropna()
                        if len(col):
                            prices[s] = float(col.iloc[-1])
    except Exception as e:
        log(f"[uyarı] toplu canlı fiyat hatası: {e}")
    # Eksik kalanlar için tek tek dene
    for s in symbols:
        if s not in prices:
            try:
                h = yf.Ticker(s).history(period="1d", interval="1m")
                col = h["Close"].dropna() if len(h) else h["Close"]
                if len(col):
                    prices[s] = float(col.iloc[-1])
            except Exception:
                pass
    return prices


# --------------------------------------------------------------------------- #
#  SCAN: günlük aday seçimi
# --------------------------------------------------------------------------- #
def run_scan(args):
    tickers_map = INDEX_MAP[args.index]
    tickers = list(tickers_map.keys())
    log(f"[scan] Katilim {args.index}: {len(tickers)} hisse, {args.period}g veri...")

    raw = fetcher.fetch_all(tickers, period_days=args.period)
    log(f"[scan] {len(raw)}/{len(tickers)} hisse alındı.")

    ranked = []
    for sym, df in raw.items():
        name = tickers_map.get(sym, sym.replace(".IS", ""))
        ind = analyzer.compute(df, sym, name)
        if ind:
            ranked.append(scorer.score_stock(ind))
    ranked.sort(key=lambda s: s.score, reverse=True)

    # ---- Aday filtresi: sadece işlem edilebilir, teyitli kurulumlar ----
    watchlist = []
    for s in ranked:
        if s.strategy == "Kaçın / İzle" or s.ind.falling_knife or s.ind.illiquid:
            continue
        if s.score < args.min_score:
            continue
        if s.risk_reward < args.min_rr:
            continue
        watchlist.append({
            "symbol": s.symbol.replace(".IS", ""),
            "yf_symbol": s.symbol,
            "name": s.name,
            "score": s.score,
            "grade": s.grade,
            "strategy": s.strategy,
            "entry": s.entry_price,
            "stop": s.stop_loss,
            "target": s.target_price,
            "rr": s.risk_reward,
            "rsi": round(s.ind.rsi14, 1),
            "reasons": s.reasons,
            "risks": s.risks,
        })
        if len(watchlist) >= args.max_positions:
            break

    payload = {
        "mode": "scan",
        "generated_at": now_iso(),
        "index": args.index,
        "candidate_count": len(watchlist),
        "params": {"min_score": args.min_score, "min_rr": args.min_rr,
                   "max_positions": args.max_positions},
        "watchlist": watchlist,
        "note": ("Bugün filtreyi geçen kurulum yok — piyasa zayıf, AL aceleci olma."
                 if not watchlist else
                 "Bu adayları monitor modu seviyelere karşı izleyecek."),
        "disclaimer": "Yatırım tavsiyesi değildir. Teyit edin, riskinizi yönetin.",
    }
    save_json(WATCHLIST_FILE, payload)

    # Açık olmayan (CLOSED) eski pozisyonları temizle ki yeniden tetiklenebilsinler
    positions = load_json(POSITIONS_FILE, {})
    positions = {k: v for k, v in positions.items() if v.get("state") == "OPEN"}
    save_json(POSITIONS_FILE, positions)

    log(f"[scan] {len(watchlist)} aday watchlist.json'a yazıldı. "
        f"Açık pozisyon korunan: {len(positions)}")
    emit(payload)


# --------------------------------------------------------------------------- #
#  MONITOR: seans içi tetik + durum makinesi
# --------------------------------------------------------------------------- #
def run_monitor(args):
    market_open = is_market_open(force=args.force)
    wl = load_json(WATCHLIST_FILE, None)
    positions = load_json(POSITIONS_FILE, {})

    if wl is None:
        emit({"mode": "monitor", "generated_at": now_iso(), "market_open": market_open,
              "signals": [], "note": "watchlist.json yok — önce 'scan' çalıştırın."})
        return

    if not market_open:
        emit({"mode": "monitor", "generated_at": now_iso(), "market_open": False,
              "signals": [], "open_positions": sum(1 for p in positions.values()
                                                   if p.get("state") == "OPEN"),
              "note": "Piyasa kapalı — işlem yok. (--force ile test edebilirsiniz.)"})
        return

    wl_items = {it["yf_symbol"]: it for it in wl.get("watchlist", [])}
    # İzlenecek semboller: watchlist + açık pozisyonlar (listeden düşse bile yönetilir)
    symbols = set(wl_items.keys()) | {
        s for s, p in positions.items() if p.get("state") == "OPEN"}
    prices = fetch_live_prices(list(symbols))

    signals = []
    buy_tol = args.buy_tol / 100.0
    missed_tol = args.missed_tol / 100.0

    for sym in symbols:
        price = prices.get(sym)
        item = wl_items.get(sym)
        pos = positions.get(sym)
        short = sym.replace(".IS", "")

        if price is None:
            signals.append({"symbol": short, "action": "VERİ_YOK",
                            "reason": "Canlı fiyat alınamadı"})
            continue

        # ---------- AÇIK pozisyon yönetimi ----------
        if pos and pos.get("state") == "OPEN":
            stop, target, fill = pos["stop"], pos["target"], pos["fill"]
            pnl = (price - fill) / fill * 100
            if price <= stop:
                pos["state"] = "CLOSED"; pos["closed_at"] = now_iso()
                pos["exit"] = price; pos["exit_reason"] = "stop"
                signals.append({"symbol": short, "action": "SAT", "price": round(price, 2),
                                "reason": "Stop tetiklendi → zararı kes",
                                "fill": fill, "pnl_pct": round(pnl, 2), "state": "CLOSED"})
            elif price >= target:
                pos["state"] = "CLOSED"; pos["closed_at"] = now_iso()
                pos["exit"] = price; pos["exit_reason"] = "target"
                signals.append({"symbol": short, "action": "SAT", "price": round(price, 2),
                                "reason": "Hedefe ulaşıldı → kâr al",
                                "fill": fill, "pnl_pct": round(pnl, 2), "state": "CLOSED"})
            else:
                signals.append({"symbol": short, "action": "TUT", "price": round(price, 2),
                                "reason": "Pozisyon açık, seviyeler korunuyor",
                                "fill": fill, "stop": stop, "target": target,
                                "unrealized_pct": round(pnl, 2), "state": "OPEN"})
            continue

        # ---------- WATCH: giriş tetiği ----------
        if item is None:
            continue  # ne açık ne izlemede
        entry, stop, target = item["entry"], item["stop"], item["target"]

        if price <= stop:
            signals.append({"symbol": short, "action": "İPTAL", "price": round(price, 2),
                            "reason": "Fiyat zaten stop altında → kurulum geçersiz, alma",
                            "entry": entry, "stop": stop, "state": "WATCH"})
        elif price > entry * (1 + missed_tol):
            signals.append({"symbol": short, "action": "İPTAL", "price": round(price, 2),
                            "reason": f"Fiyat girişi >%{args.missed_tol:.0f} aştı → kaçırıldı, kovalama",
                            "entry": entry, "state": "WATCH"})
        elif price <= entry * (1 + buy_tol):
            # Giriş bölgesinde (girişte veya hafif altında) → AL
            positions[sym] = {"state": "OPEN", "fill": round(price, 2),
                              "stop": stop, "target": target, "score": item["score"],
                              "strategy": item["strategy"], "opened_at": now_iso()}
            rr = round((target - price) / (price - stop), 2) if price > stop else 0.0
            signals.append({"symbol": short, "action": "AL", "price": round(price, 2),
                            "reason": f"Fiyat giriş bölgesinde ({item['strategy']})",
                            "entry": entry, "stop": stop, "target": target,
                            "rr": rr, "score": item["score"], "state": "OPEN"})
        else:
            signals.append({"symbol": short, "action": "BEKLE", "price": round(price, 2),
                            "reason": "Fiyat giriş bölgesinin üstünde → geri çekilmeyi bekle",
                            "entry": entry, "stop": stop, "target": target, "state": "WATCH"})

    save_json(POSITIONS_FILE, positions)

    # Aksiyon önceliğine göre sırala (AL/SAT en üstte)
    order = {"SAT": 0, "AL": 1, "TUT": 2, "BEKLE": 3, "İPTAL": 4, "VERİ_YOK": 5}
    signals.sort(key=lambda s: order.get(s["action"], 9))

    payload = {
        "mode": "monitor",
        "generated_at": now_iso(),
        "market_open": True,
        "open_positions": sum(1 for p in positions.values() if p.get("state") == "OPEN"),
        "actionable": [s for s in signals if s["action"] in ("AL", "SAT")],
        "signals": signals,
        "note": "AL/SAT 'actionable' alanında. Fiyatlar ~15dk gecikmeli olabilir.",
        "disclaimer": "Yatırım tavsiyesi değildir.",
    }
    log(f"[monitor] {len(signals)} sinyal | açık: {payload['open_positions']} | "
        f"aksiyon: {len(payload['actionable'])}")
    emit(payload)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="BIST AL/SAT sinyal motoru (ajan-dostu JSON)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan", help="Günlük aday seçimi (kapanış sonrası)")
    sc.add_argument("--index", choices=["30", "50", "100"], default="30")
    sc.add_argument("--period", type=int, default=365)
    sc.add_argument("--min-score", type=int, default=30, dest="min_score")
    sc.add_argument("--min-rr", type=float, default=1.0, dest="min_rr")
    sc.add_argument("--max-positions", type=int, default=8, dest="max_positions")

    mo = sub.add_parser("monitor", help="Seans içi tetik izleme (her ~10dk)")
    mo.add_argument("--index", choices=["30", "50", "100"], default="30")
    mo.add_argument("--buy-tol", type=float, default=0.5, dest="buy_tol",
                    help="Giriş bölgesi toleransı %% (varsayilan 0.5)")
    mo.add_argument("--missed-tol", type=float, default=3.0, dest="missed_tol",
                    help="Bu %% üstünde giriş kaçırıldı sayılır (varsayilan 3.0)")
    mo.add_argument("--force", action="store_true", help="Piyasa kapalı olsa da çalış (test)")

    args = p.parse_args()
    if args.cmd == "scan":
        run_scan(args)
    elif args.cmd == "monitor":
        run_monitor(args)


if __name__ == "__main__":
    main()
