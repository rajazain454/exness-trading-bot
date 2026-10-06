import sys
import os
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

def check_account_status():
    """Displays detailed information about the connected Exness account."""
    from mt5_connector import MT5Connector
    import config

    connector = MT5Connector()
    if not connector.initialize():
        console.print("[bold red]Could not connect to MT5. Ensure MetaTrader 5 is running.[/bold red]")
        return

    acc = connector.get_account_summary()
    valid_sym = connector.verify_symbol(config.SYMBOL)
    tick = connector.get_symbol_tick(valid_sym) if valid_sym else None
    spread = connector.get_current_spread_pips(valid_sym) if valid_sym else 0.0

    table = Table(title="Exness Account & Market Status", style="cyan")
    table.add_column("Property", style="bold white")
    table.add_column("Value", style="bold green")

    table.add_row("Account Login", str(acc.get("login")))
    table.add_row("Server", str(acc.get("server")))
    table.add_row("Balance", f"${acc.get('balance', 0.0):.2f}")
    table.add_row("Equity", f"${acc.get('equity', 0.0):.2f}")
    table.add_row("Free Margin", f"${acc.get('free_margin', 0.0):.2f}")
    table.add_row("Leverage", f"1:{acc.get('leverage')}")
    table.add_row("Trading Allowed", "YES" if acc.get("trade_allowed") else "NO (Check Algo Trading button in MT5)")
    table.add_row("Configured Symbol", f"{valid_sym}")
    table.add_row("Current Spread", f"{spread:.1f} pips")
    if tick:
        table.add_row("Live Bid / Ask", f"{tick.bid:.5f} / {tick.ask:.5f}")

    console.print(table)
    connector.shutdown()

def view_journal():
    """Displays statistics and logged trades from the SQLite Trade Journal."""
    from journal import TradeJournal
    journal = TradeJournal()
    stats = journal.get_all_time_stats()
    today = journal.get_today_summary()

    table = Table(title="Trade Journal & Performance Analytics", style="magenta")
    table.add_column("Metric", style="bold white")
    table.add_column("Value", style="bold green")

    table.add_row("Lifetime Closed Trades", str(stats.get("total", 0)))
    table.add_row("Lifetime Win Rate", f"{stats.get('win_rate', 0.0)}% ({stats.get('wins', 0)}W / {stats.get('losses', 0)}L)")
    table.add_row("Lifetime Net P&L", f"${stats.get('net_pnl', 0.0):+.2f}")
    table.add_row("Profit Factor", f"{stats.get('profit_factor', 0.0):.2f}")
    table.add_row("Today's Closed Trades", str(today.get("total", 0)))
    table.add_row("Today's Net P&L", f"${today.get('net_pnl', 0.0):+.2f} ({today.get('total_pips', 0.0):+.1f} pips)")

    console.print(table)

def main():
    while True:
        console.print("\n")
        console.print(Panel.fit(
            "[bold cyan]EXNESS INSTITUTIONAL TRADING SUITE[/bold cyan]\n"
            "[white]Designed for $30 capital, 1:50 leverage, multi-pair basket scanning, & ADX filtering[/white]",
            border_style="cyan"
        ))

        console.print("[1] [bold green]Start Live Trading Bot[/bold green] (Multi-pair basket scanning with real-time UI)")
        console.print("[2] [bold blue]Run 6-Factor Quant Backtest[/bold blue] (Benchmark vs Quant Comparison)")
        console.print("[3] [bold yellow]Inspect Exness Account & Market Status[/bold yellow]")
        console.print("[4] [bold magenta]View SQLite Trade Journal & Analytics[/bold magenta]")
        console.print("[5] [bold cyan]Run Extreme Stress Test Suite[/bold cyan] (5-tier math, broker checks, and gatekeeper diagnostics)")
        console.print("[6] [bold white]Train / Refresh 1-Year Coin Models[/bold white] (100k bars vectorized parameter optimization)")
        console.print("[7] [bold red]Exit[/bold red]")

        choice = Prompt.ask("\nSelect an option", choices=["1", "2", "3", "4", "5", "6", "7"], default="1")

        if choice == "1":
            from bot import ExnessTradingBot
            bot = ExnessTradingBot()
            bot.start()
        elif choice == "2":
            from backtester import run_full_quant_backtest
            bars = Prompt.ask("Enter number of M5 historical candles to test", default="2500")
            try:
                run_full_quant_backtest(bars=int(bars))
            except Exception as e:
                console.print(f"[red]Backtest error: {e}[/red]")
        elif choice == "3":
            check_account_status()
        elif choice == "4":
            view_journal()
        elif choice == "5":
            try:
                test_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests")
                if test_dir not in sys.path:
                    sys.path.append(test_dir)
                import importlib
                ext_module = importlib.import_module("extreme_test")
                ext_module.main()
            except Exception as e:
                console.print(f"[red]Extreme test error: {e}[/red]")
        elif choice == "6":
            from train_1year_all_coins import main as run_train_coins
            try:
                run_train_coins()
            except Exception as e:
                console.print(f"[red]Training error: {e}[/red]")
        elif choice == "7":
            console.print("[cyan]Exiting Exness Trading Bot. Happy Trading![/cyan]")
            break

if __name__ == "__main__":
    main()
