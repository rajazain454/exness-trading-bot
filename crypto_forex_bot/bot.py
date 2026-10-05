import time
import sys
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import MetaTrader5 as mt5

import config
from mt5_connector import MT5Connector
from strategy import ForexConfluenceStrategy
from risk_manager import RiskManager
from order_manager import OrderManager
from csm import CurrencyStrengthMeter
from smc import SmartMoneyConcepts

console = Console()

class ExnessTradingBot:
    """
    Enterprise-grade algorithmic trading suite for Exness.
    Incorporates multi-pair basket scanning, ADX trend strength filtering,
    Smart Money Concepts (SMC) resistance/support traps & FVG imbalances,
    Currency Strength Meter (CSM), Execution Latency & Slippage Monitoring,
    Price Action Wicks & Volume surge confirmation,
    Flash Crash Spread Anomaly Shield, Smart Partial Take-Profits,
    SQLite journaling, and Discord push digests.
    """

    def __init__(self):
        self.connector = MT5Connector()
        self.strategy = ForexConfluenceStrategy()
        self.csm = None
        self.smc = None
        self.risk_manager = None
        self.order_manager = None
        self.basket_symbols = []
        self.running = False
        self.logs = []
        self.start_time = datetime.now(timezone.utc)
        self.last_heartbeat_time = datetime.now(timezone.utc)
        self.daily_report_date = None

    def log(self, message: str, level: str = "INFO"):
        """Appends a timestamped log to the event log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] [{level}] {message}")
        if len(self.logs) > 7:
            self.logs.pop(0)

    def setup(self) -> bool:
        """Initializes connection to Exness MT5, CSM, SMC, and resolves basket symbols."""
        self.log("Connecting to Exness MT5 platform...", "INFO")
        if not self.connector.initialize():
            self.log("Failed to connect to MT5. Ensure MetaTrader 5 is running.", "ERROR")
            return False

        # Resolve symbols for basket scanner
        raw_symbols = config.SYMBOLS_BASKET if config.USE_MULTI_PAIR_BASKET else [config.SYMBOL]
        self.basket_symbols = []
        for s in raw_symbols:
            valid = self.connector.verify_symbol(s)
            if valid and valid not in self.basket_symbols:
                self.basket_symbols.append(valid)

        if not self.basket_symbols:
            self.log("No valid symbols could be verified on Exness.", "ERROR")
            return False

        self.csm = CurrencyStrengthMeter(self.connector)
        self.smc = SmartMoneyConcepts(self.connector)
        self.risk_manager = RiskManager(self.connector)
        self.order_manager = OrderManager(self.connector, risk_manager=self.risk_manager)

        if config.NEWS_FILTER_ENABLED:
            self.risk_manager.news_filter.fetch_calendar()

        discord_status = "Connected" if self.order_manager.notifier.enabled else "Disabled"
        self.log(f"Basket: {', '.join(self.basket_symbols)} | Mode: {config.ENTRY_ORDER_TYPE} | Discord: {discord_status}", "SUCCESS")
        return True

    def check_heartbeat(self):
        """Dispatches operational heartbeat to Discord periodically."""
        now = datetime.now(timezone.utc)
        interval = timedelta(minutes=config.HEARTBEAT_INTERVAL_MINUTES)
        if (now - self.last_heartbeat_time) >= interval:
            acc = self.connector.get_account_summary()
            if acc:
                uptime = str(now - self.start_time).split(".")[0]
                self.order_manager.notifier.notify_heartbeat(
                    account=acc.get("login", 0),
                    server=acc.get("server", ""),
                    balance=acc.get("balance", 0.0),
                    uptime_str=uptime
                )
            self.last_heartbeat_time = now

    def check_daily_report(self):
        """Sends daily performance digest to Discord at target UTC hour."""
        now_utc = datetime.now(timezone.utc)
        today = now_utc.date()
        if now_utc.hour >= config.DAILY_REPORT_HOUR_UTC and self.daily_report_date != today:
            summary = self.order_manager.journal.get_today_summary()
            acc = self.connector.get_account_summary()
            if acc and summary["total"] > 0:
                self.order_manager.notifier.notify_daily_summary(
                    summary=summary,
                    balance=acc.get("balance", 0.0),
                    equity=acc.get("equity", 0.0)
                )
            self.daily_report_date = today

    def build_dashboard(self, top_candidate: dict, active_positions: list) -> Layout:
        """Creates an informative live dashboard UI using Rich."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", size=10),
            Layout(name="positions", size=7),
            Layout(name="logs", size=8),
        )

        acc = self.connector.get_account_summary()
        now_utc = datetime.now(timezone.utc)

        # 1. Header
        header_text = Text()
        header_text.append("[EXNESS INSTITUTIONAL SMC ALGORITHMIC SUITE]", style="bold cyan")
        header_text.append(f"  |  Account: {acc.get('login', 'N/A')} ({acc.get('server', 'N/A')})", style="bold yellow")
        header_text.append(f"  |  Execution: {config.ENTRY_ORDER_TYPE}", style="bold green")
        header_text.append(f"  |  UTC: {now_utc.strftime('%H:%M:%S')}", style="bold white")
        layout["header"].update(Panel(header_text, style="cyan"))

        # 2. Main split: Account/CSM (Left) & Scanner/SMC (Right)
        layout["main"].split_row(
            Layout(name="account_box", ratio=1),
            Layout(name="scanner_box", ratio=1),
        )

        # Account Box
        balance = acc.get("balance", 0.0)
        equity = acc.get("equity", 0.0)
        free_margin = acc.get("free_margin", 0.0)
        floating_pnl = equity - balance
        pnl_style = "bold green" if floating_pnl >= 0 else "bold red"
        compounded_lot = self.risk_manager.calculate_lot_size(equity) if self.risk_manager else 0.01

        stats = self.order_manager.journal.get_today_summary() if self.order_manager else {}
        today_pnl = stats.get("net_pnl", 0.0)
        today_pnl_style = "bold green" if today_pnl >= 0 else "bold red"

        csm_scores = self.csm.cached_scores if self.csm else {}
        csm_str = " | ".join(f"{k}:{v:+.1f}" for k, v in list(csm_scores.items())[:4]) if csm_scores else "Calculating..."

        acc_table = Table(box=None, expand=True)
        acc_table.add_column("Property", style="dim white")
        acc_table.add_column("Value", justify="right")
        acc_table.add_row("Balance / Equity", f"${balance:.2f} / ${equity:.2f}")
        acc_table.add_row("Floating P&L", f"[{pnl_style}]${floating_pnl:+.2f}[/{pnl_style}]")
        acc_table.add_row("Today's Closed P&L", f"[{today_pnl_style}]${today_pnl:+.2f}[/{today_pnl_style}] ({stats.get('wins', 0)}W/{stats.get('losses', 0)}L)")
        acc_table.add_row("Free Margin", f"${free_margin:.2f}")
        acc_table.add_row("Active Lot Sizing", f"[bold cyan]{compounded_lot:.2f} Lot[/bold cyan] (Kelly: {'ON' if config.USE_KELLY_SIZING else 'OFF'})")
        acc_table.add_row("CSM Relative Strength", f"[bold yellow]{csm_str}[/bold yellow]")

        layout["account_box"].update(Panel(acc_table, title="[bold]Financials & Currency Strength (CSM)[/bold]", border_style="blue"))

        # Scanner & SMC Box
        sym = top_candidate.get("symbol", self.basket_symbols[0] if self.basket_symbols else "EURUSDm")
        sig = top_candidate.get("signal", "HOLD")
        score = top_candidate.get("score", 0)
        metrics = top_candidate.get("metrics", {})
        spread = self.connector.get_current_spread_pips(sym)
        levels = self.smc.daily_levels_cache.get(sym, {}) if self.smc else {}

        sig_style = "bold green" if sig == "BUY" else ("bold red" if sig == "SELL" else "bold yellow")

        scan_table = Table(box=None, expand=True)
        scan_table.add_column("Metric", style="dim white")
        scan_table.add_column("Status", justify="right")
        scan_table.add_row("Basket Focus", f"[bold]{sym}[/bold] (Spread: {spread:.1f} p)")
        scan_table.add_row("MTF Trend (M5/H1)", f"{metrics.get('m5_trend', 'N/A')} / [bold]{metrics.get('h1_trend', 'N/A')}[/bold]")
        scan_table.add_row("Quant Z / CHOP", f"Z: {metrics.get('z_score', 0.0):+.2f} | CHOP: {metrics.get('chop', 0.0):.1f} ({'Trend' if metrics.get('chop', 50) < 61.8 else 'Consol'})")
        scan_table.add_row("VWAP / ATR Rank", f"VWAP: {metrics.get('vwap', 0.0):.5f} | ATR Rank: {metrics.get('atr_pct', 50.0):.1f}%")
        scan_table.add_row("ADX / Volume", f"ADX: {metrics.get('adx', 0.0):.1f} | Vol: {metrics.get('vol_ratio', 0.0):.2f}x")
        scan_table.add_row("SMC Daily Range", f"PDH: {levels.get('pdh', 0.0):.5f} | PDL: {levels.get('pdl', 0.0):.5f}")
        scan_table.add_row("Imbalance (FVG)", f"{metrics.get('fvg', 'NONE')}")
        scan_table.add_row("Confluence Score", f"[{sig_style}]{sig}[/{sig_style}] (Score: {score}/100)")
        layout["scanner_box"].update(Panel(scan_table, title="[bold]SMC Market Structure & Confluence[/bold]", border_style="magenta"))

        # 3. Active Positions
        pos_table = Table(expand=True)
        pos_table.add_column("Ticket", justify="center")
        pos_table.add_column("Symbol", justify="center")
        pos_table.add_column("Type", justify="center")
        pos_table.add_column("Lot", justify="center")
        pos_table.add_column("Open Price", justify="right")
        pos_table.add_column("Current Price", justify="right")
        pos_table.add_column("SL", justify="right")
        pos_table.add_column("TP", justify="right")
        pos_table.add_column("Profit ($)", justify="right")

        if active_positions:
            for p in active_positions:
                p_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                type_style = "green" if p_type == "BUY" else "red"
                p_style = "bold green" if p.profit >= 0 else "bold red"
                pos_table.add_row(
                    str(p.ticket),
                    p.symbol,
                    f"[{type_style}]{p_type}[/{type_style}]",
                    f"{p.volume:.2f}",
                    f"{p.price_open:.5f}",
                    f"{p.price_current:.5f}",
                    f"{p.sl:.5f}",
                    f"{p.tp:.5f}",
                    f"[{p_style}]${p.profit:+.2f}[/{p_style}]"
                )
        else:
            pos_table.add_row("-", "-", "NO ACTIVE POSITIONS", "-", "-", "-", "-", "-", "$0.00")

        layout["positions"].update(Panel(pos_table, title="[bold]Active Positions (Synced with Exness Web & App)[/bold]", border_style="green"))

        # 4. Logs panel
        log_text = "\n".join(self.logs) if self.logs else "Monitoring basket & structure..."
        layout["logs"].update(Panel(log_text, title="[bold]Execution & Safety Log Feed[/bold]", border_style="yellow"))

        return layout

    def scan_basket(self) -> dict:
        """Scans all basket symbols with CSM, SMC, and Confluence filters."""
        if self.csm:
            self.csm.calculate_strengths()

        best_candidate = {
            "symbol": self.basket_symbols[0] if self.basket_symbols else "EURUSDm",
            "signal": "HOLD",
            "score": -1,
            "metrics": {},
            "reason": ""
        }

        for sym in self.basket_symbols:
            m5_rates = self.connector.get_rates(sym, config.TIMEFRAME, count=250)
            h1_rates = self.connector.get_rates(sym, config.HIGHER_TIMEFRAME, count=250)
            analysis = self.strategy.analyze(m5_rates, h1_rates, csm_engine=self.csm, smc_engine=self.smc, symbol=sym)

            score = analysis.get("score", 0)
            sig = analysis.get("signal", "HOLD")

            if sig in ["BUY", "SELL"] and score > best_candidate["score"]:
                best_candidate = {
                    "symbol": sym,
                    "signal": sig,
                    "score": score,
                    "metrics": analysis.get("metrics", {}),
                    "reason": analysis.get("reason", "")
                }
            elif best_candidate["score"] < 0:
                best_candidate = {
                    "symbol": sym,
                    "signal": sig,
                    "score": score,
                    "metrics": analysis.get("metrics", {}),
                    "reason": analysis.get("reason", "")
                }

        return best_candidate

    def start(self):
        """Main automated trading loop."""
        if not self.setup():
            console.print("[bold red]Bot setup failed. Exiting.[/bold red]")
            return

        self.running = True
        self.log(f"Bot engine running. Mode: {config.ENTRY_ORDER_TYPE} | Monitoring basket & SMC structure...", "SUCCESS")

        try:
            with Live(console=console, refresh_per_second=2, screen=False) as live:
                while self.running:
                    # 1. Connection Health & Auto-Recovery
                    if not self.connector.ensure_connection():
                        self.log("Reconnecting to Exness MT5...", "WARNING")
                        time.sleep(3)
                        continue

                    # 2. Check Friday Market Cutoff and Cancel Expired Limit Orders
                    self.order_manager.check_friday_auto_close(self.basket_symbols)
                    self.order_manager.cancel_expired_pending_orders()

                    # 3. Check Heartbeat and Daily Digest
                    self.check_heartbeat()
                    self.check_daily_report()

                    # 4. Manage active positions across all basket symbols (Partial TP, BE, Trailing Stop)
                    for sym in self.basket_symbols:
                        self.order_manager.manage_trailing_and_breakeven(sym)
                    active_positions = self.order_manager.get_bot_positions()
                    total_active_and_pending = self.order_manager.get_bot_active_and_pending_count()

                    # 5. Scan basket for top setup
                    top_candidate = self.scan_basket()
                    top_sym = top_candidate["symbol"]
                    sig = top_candidate["signal"]
                    metrics = top_candidate.get("metrics", {})

                    # 6. Execute trade if valid signal and risk checks pass
                    if sig in ["BUY", "SELL"]:
                        can_trade, reason = self.risk_manager.can_open_trade(top_sym, total_active_and_pending)
                        if can_trade:
                            atr_val = metrics.get("atr", 0.0)
                            atr_pct = metrics.get("atr_pct", 50.0)
                            trade_params = self.risk_manager.calculate_sl_tp(top_sym, sig, atr_value=atr_val, atr_percentile=atr_pct)
                            if trade_params:
                                ticket = self.order_manager.open_position(top_sym, sig, trade_params)
                                if ticket:
                                    self.log(
                                        f"Executed {sig} on {top_sym} #{ticket} @ {trade_params['entry']} | "
                                        f"Lot: {trade_params['lot']} | SL: {trade_params['sl']} | TP: {trade_params['tp']}",
                                        "TRADE"
                                    )
                        else:
                            if "limit (1) reached" not in reason:
                                self.log(f"Signal {sig} on {top_sym} skipped: {reason}", "FILTER")

                    # 7. Render updated dashboard
                    dashboard = self.build_dashboard(top_candidate, active_positions)
                    live.update(dashboard)

                    time.sleep(config.SLEEP_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            self.log("Shutdown requested by user (Ctrl+C).", "INFO")
        except Exception as e:
            import traceback
            console.print(f"[bold red]Runtime error in bot:[/bold red]")
            traceback.print_exc()
            self.log(f"Runtime error: {str(e)}", "ERROR")
        finally:
            self.stop()

    def stop(self):
        """Safely shuts down bot, flushes notifier, and closes connector."""
        self.running = False
        if self.order_manager and self.order_manager.notifier:
            self.order_manager.notifier.shutdown()
        self.connector.shutdown()
        console.print("[bold green]Exness Trading Bot stopped safely.[/bold green]")

if __name__ == "__main__":
    bot = ExnessTradingBot()
    bot.start()
