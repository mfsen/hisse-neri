"""Rich ile renkli terminal çıktısı."""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.rule import Rule
from rich import box
from scorer import StockScore
from typing import List

console = Console()

GRADE_COLOR = {"A+": "bold green", "A": "green", "B": "yellow", "C": "orange1", "D": "red"}
STRATEGY_COLOR = {
    "Reversal (Dip Alım)": "cyan",
    "Trend Takibi": "green",
    "Momentum": "magenta",
    "Swing Trade": "yellow",
}


def _score_bar(score: int) -> Text:
    filled = score // 5
    empty = 20 - filled
    bar = Text()
    if score >= 65:
        bar.append("█" * filled, style="green")
    elif score >= 45:
        bar.append("█" * filled, style="yellow")
    else:
        bar.append("█" * filled, style="red")
    bar.append("░" * empty, style="dim")
    bar.append(f"  {score}/100")
    return bar


def print_market_summary(summary: dict):
    console.print()
    panels = []
    for label, data in summary.items():
        chg = data["change_pct"]
        color = "green" if chg >= 0 else "red"
        arrow = "▲" if chg >= 0 else "▼"
        price_str = f"{data['price']:,.2f}"
        chg_str = f"{arrow} {abs(chg):.2f}%"
        panels.append(Panel(
            f"[bold]{price_str}[/bold]\n[{color}]{chg_str}[/{color}]",
            title=f"[bold]{label}[/bold]",
            expand=False,
            border_style=color,
        ))
    if panels:
        console.print(Columns(panels))
    console.print()


def print_top_table(scores: List[StockScore], top_n: int = 15):
    table = Table(
        title=f"[bold]BIST Katilim Endeksi — Top {top_n} Alim Adayi[/bold]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Hisse", style="bold", width=12)
    table.add_column("Ad", width=18)
    table.add_column("Skor", width=26)
    table.add_column("Not", width=4, justify="center")
    table.add_column("Strateji", width=20)
    table.add_column("Fiyat", justify="right", width=10)
    table.add_column("RSI", justify="right", width=6)
    table.add_column("Δ1G", justify="right", width=7)
    table.add_column("Δ5G", justify="right", width=7)
    table.add_column("Hacim×", justify="right", width=7)

    for i, s in enumerate(scores[:top_n], 1):
        ind = s.ind
        grade_style = GRADE_COLOR.get(s.grade, "white")
        strat_style = STRATEGY_COLOR.get(s.strategy, "white")

        chg1_color = "green" if ind.change_1d >= 0 else "red"
        chg5_color = "green" if ind.change_5d >= 0 else "red"
        rsi_color = "cyan" if ind.rsi14 < 35 else ("red" if ind.rsi14 > 70 else "white")

        table.add_row(
            str(i),
            s.symbol.replace(".IS", ""),
            s.name[:18],
            _score_bar(s.score),
            f"[{grade_style}]{s.grade}[/{grade_style}]",
            f"[{strat_style}]{s.strategy}[/{strat_style}]",
            f"{ind.last_price:,.2f} ₺",
            f"[{rsi_color}]{ind.rsi14:.1f}[/{rsi_color}]",
            f"[{chg1_color}]{ind.change_1d:+.1f}%[/{chg1_color}]",
            f"[{chg5_color}]{ind.change_5d:+.1f}%[/{chg5_color}]",
            f"{ind.volume_ratio:.2f}×",
        )

    console.print(table)


def print_detail(s: StockScore):
    ind = s.ind
    grade_style = GRADE_COLOR.get(s.grade, "white")

    title = (f"[bold]{s.name}[/bold]  [{grade_style}]{s.grade}[/{grade_style}]  "
             f"({s.symbol})  Skor: {s.score}/100")
    console.print(Rule(title, style="cyan"))

    # Sol sütun: İndikatörler
    ind_lines = [
        f"  Fiyat      : [bold]{ind.last_price:,.2f} ₺[/bold]",
        f"  SMA20/50   : {ind.sma20:,.2f} / {ind.sma50:,.2f}",
        f"  SMA200     : {ind.sma200:,.2f}  {'[green]↑ Üzeri[/green]' if ind.above_sma200 else '[red]↓ Altı[/red]'}",
        f"  RSI(14)    : [{'cyan' if ind.rsi14<35 else 'red' if ind.rsi14>70 else 'white'}]{ind.rsi14:.1f}[/]",
        f"  MACD/Sig   : {ind.macd:.2f} / {ind.macd_signal:.2f}  hist={ind.macd_hist:+.2f}",
        f"  BB %b      : {ind.bb_pct:.2f}  [{ind.bb_lower:,.2f} – {ind.bb_upper:,.2f}]",
        f"  Stoch K/D  : {ind.stoch_k:.1f} / {ind.stoch_d:.1f}",
        f"  ATR(14)    : {ind.atr14:.2f}",
        f"  Hacim×     : {ind.volume_ratio:.2f}",
        f"  Δ1G/5G/20G : {ind.change_1d:+.1f}% / {ind.change_5d:+.1f}% / {ind.change_20d:+.1f}%",
        f"  52H Dip    : {ind.week52_low:,.2f}  (+{ind.dist_from_52w_low:.1f}%)",
        f"  52H Zirve  : {ind.week52_high:,.2f}",
    ]

    # Sağ sütun: Trade planı
    rr_color = "green" if s.risk_reward >= 2 else "yellow" if s.risk_reward >= 1 else "red"
    trade_lines = [
        f"  Strateji   : [bold]{s.strategy}[/bold]",
        f"  Giriş      : [bold]{s.entry_price:,.2f} ₺[/bold]",
        f"  Stop Loss  : [red]{s.stop_loss:,.2f} ₺[/red]",
        f"  Hedef      : [green]{s.target_price:,.2f} ₺[/green]",
        f"  Risk/Ödül  : [{rr_color}]{s.risk_reward:.1f}x[/{rr_color}]",
    ]

    left = "\n".join(ind_lines)
    right = "\n".join(trade_lines)
    console.print(Columns([
        Panel(left, title="İndikatörler", border_style="blue", expand=True),
        Panel(right, title="Trade Planı", border_style="green", expand=True),
    ]))

    # Sinyaller
    if s.reasons:
        bullish_text = Text()
        for r in s.reasons:
            bullish_text.append(f"  ✔ {r}\n", style="green")
        console.print(Panel(bullish_text, title="[green]Bullish Sinyaller[/green]", border_style="green"))

    if s.risks:
        risk_text = Text()
        for r in s.risks:
            risk_text.append(f"  ✘ {r}\n", style="red")
        console.print(Panel(risk_text, title="[red]Riskler[/red]", border_style="red"))

    console.print()


def print_algo_tips():
    tips = """[bold cyan]Algoritmik Trading İpuçları — BIST 100[/bold cyan]

[bold]1. RSI Reversal Stratejisi[/bold]
   • RSI < 30 olduğunda giriş yap, RSI > 50 olduğunda çık
   • Stop: ATR × 1.5 aşağıda | Hedef: ATR × 3 yukarıda
   • BIST'te özellikle bankacılık ve sanayi hisselerinde etkili

[bold]2. MACD Momentum[/bold]
   • MACD çizgisi sinyal çizgisini yukarı keserken hacim >1.5× ise giriş
   • Endeks yükselen trendde iken (BIST100 SMA50 > SMA200) sinyal kalitesi artar

[bold]3. Bollinger Band Sıkışma (Squeeze)[/bold]
   • BB genişliği daralırken hacim de düşükse "coil" oluşuyor
   • Kırılma yönünde işlem aç; fiyat alt bandı kırarsa short, üst bandı kırarsa long

[bold]4. Golden Cross Trend Takibi[/bold]
   • SMA50 > SMA200 geçişinde pozisyon aç
   • Trailing stop: SMA20 altına kapanış olursa kapat

[bold]5. Hacim Profili / Breakout[/bold]
   • 52 haftalık direnç kırılırken hacim ort. > 2× ise güçlü sinyal
   • BIST'te kurumsal alım sonrası bu tip kırılmalar momentum yaratır

[bold]6. Risk Yönetimi (BIST özelinde)[/bold]
   • Portföyün max %5'ini tek hisseye koyma
   • Döviz/enflasyon döngüsünü izle: TL faiz artışı → banka hisseleri; TL devalüasyonu → ihracatçılar (THYAO, FROTO, EREGL)
   • Açıklama günleri (bilançolar, TCMB kararları) öncesi pozisyon küçült

[bold]7. Sektörel Rotasyon[/bold]
   • Faiz düşerken: GYO, banka
   • Enflasyon döneminde: çelik, enerji, hammadde
   • Güçlü dolar: THYAO, FROTO, KOZAL (dolar geliri)
"""
    console.print(Panel(tips, title="[bold]Algoritmik Trading Rehberi[/bold]", border_style="cyan"))


def print_failed(failed: List[str]):
    if failed:
        console.print(f"[dim]Veri alınamayan hisseler ({len(failed)}): {', '.join(failed)}[/dim]")
