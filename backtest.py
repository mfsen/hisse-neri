"""
Skor → getiri ilişkisini geçmişe dönük (walk-forward) test eder.

Amaç: scorer.py'deki ağırlıkların GERÇEKTEN tahmin gücü olup olmadığını ölçmek.
Yöntem (look-ahead YOK — point-in-time):
  • Her yeniden dengeleme tarihinde, yalnızca O GÜNE KADARKİ veriyle skor hesaplanır.
  • Sonra ileriye dönük (forward) H günlük getiri kaydedilir.
  • Skor dilimlerine göre ortalama ileri getiri, kazanma oranı ve
    "en yüksek skorlu K hisse vs evren ortalaması" farkı (alfa) raporlanır.

Kullanim:
  python backtest.py                       # Katilim 30, 2y veri, 10g ufuk
  python backtest.py --index 50 --horizon 5 --rebalance 5 --top 5
  python backtest.py --period 1000 --horizon 20

NOT: Bu yine de bir TAHMİN doğrulamasıdır, garanti değil. Yahoo verisi (bedelli/
bedelsiz düzeltmeleri) BIST'te kusurlu olabilir; sonuçları temkinli yorumlayın.
"""

import sys
import os
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich import box

import fetcher
import analyzer
import scorer
from bist100 import KATILIM30_TICKERS, KATILIM50_TICKERS, KATILIM100_TICKERS

console = Console()

MIN_HISTORY = 210  # compute() güvenilir indikatör için gereken min bar (SMA200 vb.)


def parse_args():
    p = argparse.ArgumentParser(description="BIST skor backtest (walk-forward)")
    p.add_argument("--index", choices=["30", "50", "100"], default="30")
    p.add_argument("--period", type=int, default=730,
                   help="Çekilecek geçmiş gün sayısı (varsayilan: 730 ~2y)")
    p.add_argument("--horizon", type=int, default=10,
                   help="İleriye dönük getiri ufku, işlem günü (varsayilan: 10)")
    p.add_argument("--rebalance", type=int, default=5,
                   help="Yeniden dengeleme adımı, işlem günü (varsayilan: 5)")
    p.add_argument("--top", type=int, default=5,
                   help="Alfa için en yüksek skorlu kaç hisse (varsayilan: 5)")
    return p.parse_args()


def collect_observations(raw: dict, horizon: int, rebalance: int):
    """Her (tarih, hisse) için (skor, ileri_getiri) gözlemleri toplar."""
    obs = []                       # list of (date, symbol, score, fwd_ret)
    per_date = {}                  # date -> list of (symbol, score, fwd_ret)

    # Ortak tarih ekseni: en uzun seriyi referans al
    longest = max(raw.values(), key=len)
    dates = longest.index

    # Test edilecek tarih indeksleri (yeterli geçmiş + yeterli gelecek olanlar)
    start_i = MIN_HISTORY
    end_i = len(dates) - horizon - 1
    test_idxs = range(start_i, end_i, rebalance)

    for ti in test_idxs:
        d = dates[ti]
        bucket = []
        for sym, df in raw.items():
            # Bu hissenin verisinde d tarihine kadar olan kısım
            hist = df[df.index <= d]
            if len(hist) < MIN_HISTORY:
                continue
            # Gelecek fiyat (d'den horizon işlem günü sonrası, AYNI hissede)
            future = df[df.index > d]
            if len(future) < horizon:
                continue
            ind = analyzer.compute(hist, sym, sym)
            if ind is None:
                continue
            sc = scorer.score_stock(ind)
            p0 = float(hist["Close"].iloc[-1])
            p1 = float(future["Close"].iloc[horizon - 1])
            if p0 <= 0:
                continue
            fwd = (p1 - p0) / p0 * 100.0
            obs.append((d, sym, sc.score, fwd))
            bucket.append((sym, sc.score, fwd))
        if bucket:
            per_date[d] = bucket
    return obs, per_date


def bucket_table(obs):
    """Skor dilimi → ortalama ileri getiri / kazanma oranı."""
    df = pd.DataFrame(obs, columns=["date", "symbol", "score", "fwd"])
    bins = [0, 20, 35, 50, 65, 101]
    labels = ["0-19", "20-34", "35-49", "50-64", "65+"]
    df["bucket"] = pd.cut(df["score"], bins=bins, labels=labels, right=False)

    t = Table(title="[bold]Skor Dilimi → İleri Getiri[/bold]", box=box.ROUNDED,
              header_style="bold cyan")
    t.add_column("Skor")
    t.add_column("Gözlem", justify="right")
    t.add_column("Ort. Getiri", justify="right")
    t.add_column("Medyan", justify="right")
    t.add_column("Kazanma %", justify="right")

    for lab in labels:
        sub = df[df["bucket"] == lab]
        if len(sub) == 0:
            continue
        avg = sub["fwd"].mean()
        med = sub["fwd"].median()
        win = (sub["fwd"] > 0).mean() * 100
        ac = "green" if avg > 0 else "red"
        t.add_row(lab, str(len(sub)),
                  f"[{ac}]{avg:+.2f}%[/{ac}]", f"{med:+.2f}%", f"{win:.0f}%")
    console.print(t)
    return df


def spearman(df):
    """Skor ile ileri getiri arasındaki Spearman rank korelasyonu (scipy'siz)."""
    if len(df) < 10:
        return float("nan")
    # Spearman = sıralamalar üzerinde Pearson korelasyonu
    return df["score"].rank().corr(df["fwd"].rank(), method="pearson")


def alpha_topk(per_date, top_k):
    """Her tarihte en yüksek skorlu K hisse vs evren ortalaması farkı (alfa)."""
    spreads, top_rets, uni_rets = [], [], []
    for d, bucket in per_date.items():
        if len(bucket) < top_k:
            continue
        ranked = sorted(bucket, key=lambda x: x[1], reverse=True)
        top = [r[2] for r in ranked[:top_k]]
        uni = [r[2] for r in bucket]
        t_avg, u_avg = np.mean(top), np.mean(uni)
        spreads.append(t_avg - u_avg)
        top_rets.append(t_avg)
        uni_rets.append(u_avg)
    return spreads, top_rets, uni_rets


def main():
    args = parse_args()
    index_map = {"30": KATILIM30_TICKERS, "50": KATILIM50_TICKERS,
                 "100": KATILIM100_TICKERS}
    tickers = list(index_map[args.index].keys())

    console.print(f"[cyan]Katilim {args.index} — {len(tickers)} hisse, "
                  f"{args.period}g veri çekiliyor...[/cyan]")
    raw = fetcher.fetch_all(tickers, period_days=args.period)
    console.print(f"[green]✔ {len(raw)}/{len(tickers)} hisse alındı.[/green]")
    if len(raw) < 3:
        console.print("[red]Yetersiz veri.[/red]")
        return

    console.print(f"[dim]Walk-forward: ufuk={args.horizon}g, "
                  f"adım={args.rebalance}g, top-K={args.top}[/dim]")
    obs, per_date = collect_observations(raw, args.horizon, args.rebalance)
    if not obs:
        console.print("[red]Gözlem üretilemedi (veri çok kısa olabilir).[/red]")
        return

    console.print(f"[green]✔ {len(obs)} gözlem, {len(per_date)} rebalance tarihi.[/green]\n")

    df = bucket_table(obs)
    rho = spearman(df)

    spreads, top_rets, uni_rets = alpha_topk(per_date, args.top)
    console.print()
    summary = Table(title="[bold]Özet — Modelin Tahmin Gücü[/bold]",
                    box=box.ROUNDED, header_style="bold cyan")
    summary.add_column("Metrik")
    summary.add_column("Değer", justify="right")
    summary.add_column("Yorum")

    rho_c = "green" if rho > 0.05 else "red" if rho < -0.05 else "yellow"
    summary.add_row("Spearman ρ (skor↔getiri)",
                    f"[{rho_c}]{rho:+.3f}[/{rho_c}]",
                    "Pozitif = yüksek skor → yüksek getiri (idealde >0.05)")
    if spreads:
        sp = np.mean(spreads)
        sp_c = "green" if sp > 0 else "red"
        hit = np.mean([s > 0 for s in spreads]) * 100
        summary.add_row(f"Top-{args.top} alfa (vs evren)",
                        f"[{sp_c}]{sp:+.2f}%[/{sp_c}]",
                        f"{args.horizon}g'de evren üstü ort. getiri")
        summary.add_row(f"Top-{args.top} ort. getiri",
                        f"{np.mean(top_rets):+.2f}%",
                        f"Evren ort: {np.mean(uni_rets):+.2f}%")
        summary.add_row("Alfa pozitif tarih oranı", f"{hit:.0f}%",
                        ">50% ise tutarlı")
    console.print(summary)

    console.print(
        "\n[dim]Yorum: ρ ve alfa anlamlı pozitifse skor işe yarıyor demektir. "
        "Sıfıra yakın/negatifse ağırlıklar elden geçmeli. "
        "İşlem maliyeti/kayma dahil DEĞİLDİR.[/dim]")


if __name__ == "__main__":
    main()
