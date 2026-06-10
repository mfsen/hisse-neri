"""
BIST 100 Analiz & Algoritmik Trading Oneri Araci
Kullanim:
  python main.py               - Cekirdek 40 hisse hizli analiz
  python main.py --full        - Tum BIST 100 listesi
  python main.py --ticker GARAN AKBNK THYAO
  python main.py --detail 5    - Ilk 5 hissenin detay raporu
  python main.py --tips        - Yalnizca trading ipuclari
"""

import sys
import os

# Windows UTF-8 fix (must be before any Rich import)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse

# reporter import'u için path ekle
sys.path.insert(0, os.path.dirname(__file__))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel

import fetcher
import analyzer
import scorer
import reporter
from bist100 import (KATILIM30_TICKERS, KATILIM50_TICKERS,
                     KATILIM100_TICKERS, CORE_TICKERS, BIST100_TICKERS)

console = Console()


def parse_args():
    p = argparse.ArgumentParser(description="BIST Katilim Endeksi Teknik Analiz")
    p.add_argument("--index", choices=["30", "50", "100"], default="30",
                   help="Katilim endeksi: 30 (varsayilan), 50 veya 100")
    p.add_argument("--ticker", nargs="+", metavar="SEM",
                   help="Belirli hisseler (ornek: THYAO EREGL ASELS)")
    p.add_argument("--detail", type=int, default=3, metavar="N",
                   help="Detayli rapor gosterilecek hisse sayisi (varsayilan: 3)")
    p.add_argument("--top", type=int, default=15, metavar="N",
                   help="Tabloda gosterilecek hisse sayisi (varsayilan: 15)")
    p.add_argument("--tips", action="store_true", help="Sadece trading ipuclarini goster")
    p.add_argument("--no-tips", action="store_true", help="Trading ipuclarini gizle")
    p.add_argument("--period", type=int, default=365, metavar="DAYS",
                   help="Veri cekilecek gun sayisi (varsayilan: 365)")
    return p.parse_args()


def build_ticker_map(args) -> dict:
    if args.ticker:
        tickers = [t.upper() + ".IS" if not t.endswith(".IS") else t.upper()
                   for t in args.ticker]
        all_known = {**KATILIM100_TICKERS}
        return {t: all_known.get(t, t.replace(".IS", "")) for t in tickers}
    index_map = {"30": KATILIM30_TICKERS,
                 "50": KATILIM50_TICKERS,
                 "100": KATILIM100_TICKERS}
    return index_map[args.index]


def main():
    args = parse_args()

    index_label = f"Katilim {args.index}" if not args.ticker else "Ozel Secim"
    console.print(Panel(
        f"[bold cyan]BIST {index_label} Endeksi — Teknik Analiz & Trading Oneri Sistemi[/bold cyan]\n"
        "[dim]Resmi Borsa Istanbul katilim listesi  |  RSI · MACD · Bollinger · Golden Cross · Stochastic · ATR[/dim]",
        border_style="cyan",
    ))

    if args.tips:
        reporter.print_algo_tips()
        return

    ticker_map = build_ticker_map(args)
    tickers = list(ticker_map.keys())

    # ---- Piyasa özeti ----
    console.print("[dim]Piyasa özeti alınıyor...[/dim]")
    market = fetcher.fetch_market_summary()
    if market:
        reporter.print_market_summary(market)

    # ---- Veri çekimi ----
    results = {}
    failed = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]{len(tickers)} hisse verisi çekiliyor...", total=len(tickers)
        )

        def on_progress(done, total, ticker):
            name = ticker_map.get(ticker, ticker)
            progress.update(task, advance=1,
                            description=f"[cyan]Çekiliyor: {name[:20]:<20}")

        raw = fetcher.fetch_all(tickers, period_days=args.period,
                                progress_callback=on_progress)

    console.print(f"[green]✔ {len(raw)}/{len(tickers)} hisse verisi alındı.[/green]")

    # ---- Teknik analiz ----
    indicators = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Teknik analiz hesaplanıyor...", total=len(raw))
        for sym, df in raw.items():
            name = ticker_map.get(sym, sym.replace(".IS", ""))
            ind = analyzer.compute(df, sym, name)
            if ind:
                indicators.append(ind)
            else:
                failed.append(sym)
            progress.advance(task)

    if not indicators:
        console.print("[red]Hiçbir hisse analiz edilemedi. İnternet bağlantınızı kontrol edin.[/red]")
        return

    # ---- Skorlama & sıralama ----
    ranked = scorer.rank_stocks(indicators)

    # ---- Çıktı ----
    console.print()
    reporter.print_top_table(ranked, top_n=args.top)
    console.print()

    # Detay raporları
    detail_count = min(args.detail, len(ranked))
    if detail_count > 0:
        console.print(f"\n[bold]İlk {detail_count} Hisse Detay Raporu[/bold]")
        for s in ranked[:detail_count]:
            reporter.print_detail(s)

    # Trading ipuçları
    if not args.no_tips:
        reporter.print_algo_tips()

    reporter.print_failed(failed)

    # ---- Özet satırı ----
    top3 = ", ".join(
        f"[bold]{s.symbol.replace('.IS','')}[/bold] ({s.score})"
        for s in ranked[:3]
    )
    console.print(Panel(
        f"[green]En guclu 3 alim adayi (Katilim uyumlu):[/green] {top3}\n"
        f"[dim]Analiz edilen: {len(indicators)} hisse  |  "
        f"Veri alinamayan: {len(failed)} hisse[/dim]",
        title="[bold]Ozet[/bold]",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
