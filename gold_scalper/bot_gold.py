"""
Autonomous Institutional Gold (XAUUSDm) Scalper Bot
Runs 100% independently from the multi-asset swing bot.
Executes the proven 1-year trained Gold Scalping Strategy:
- London & NY Session Liquidity Window (08:00 - 16:00 UTC)
- Fast EMA 9/21 Dynamic Value Pullback
- H1 Macro Trend Alignment
- Fractal Choppiness Filter (CHOP <= 52.0)
- Smart Partial TP (Banks 50% @ 1.0x ATR)
- Automatic Break-Even Lock (+ $0.10)
- Live Rich Terminal Dashboard
"""

import sys
import os
import time
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import MetaTrader5 as mt5

# Add parent, crypto_forex_bot, and gold_scalper directories to path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRYPTO_DIR = os.path.join(PARENT_DIR, "crypto_forex_bot")
GOLD_DIR = os.path.dirname(os.path.abspath(__file__))
for d in [PARENT_DIR, CRYPTO_DIR, GOLD_DIR]:
    if d not in sys.path:
        sys.path.insert(0, d)

import logging
from logging.handlers import RotatingFileHandler

try:
    from gold_scalper import config_gold
    from gold_scalper.strategy_gold import GoldScalperStrategy
    from gold_scalper.order_manager_gold import GoldOrderManager
except ImportError:
    import config_gold
    from strategy_gold import GoldScalperStrategy
    from order_manager_gold import GoldOrderManager

from crypto_forex_bot.mt5_connector import MT5Connector
from crypto_forex_bot.notifier import DiscordNotifier
from crypto_forex_bot.journal import TradeJournal

# Setup Rotating File Logger for permanent audit trail
os.makedirs("logs", exist_ok=True)
file_logger = logging.getLogger("GoldScalperFile")
file_logger.setLevel(logging.INFO)
if not file_logger.handlers:
    rfh = RotatingFileHandler(
        "logs/gold_scalper.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    rfh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    file_logger.addHandler(rfh)

console = Console()


class GoldScalperBot:
    """Independent Gold Scalping Bot with dedicated risk and position tracking."""

    def __init__(self):
        self.connector = MT5Connector()
        self.strategy = GoldScalperStrategy()
        self.notifier = DiscordNotifier(config_gold.DISCORD_WEBHOOK_URL)
        self.journal = TradeJournal()
        self.symbol = config_gold.SYMBOL
        self.magic = config_gold.MAGIC_NUMBER
        self.order_manager = GoldOrderManager(
            connector=self.connector,
            notifier=self.notifier,
            journal=self.journal,
        )
        self.running = False
        self.logs = []
        self.circuit_breaker_active = False
        self.circuit_breaker_until_bar = 0

        # Initialize Economic News Filter
        self.news_filter = None
        if getattr(config_gold, "NEWS_FILTER_ENABLED", True):
            try:
                from crypto_forex_bot.news_filter import EconomicNewsFilter
                pre_b = getattr(config_gold, "NEWS_PRE_BUFFER_MINS", 30)
                post_b = getattr(config_gold, "NEWS_POST_BUFFER_MINS", 30)
                self.news_filter = EconomicNewsFilter(pre_buffer_mins=pre_b, post_buffer_mins=post_b)
                self.news_filter.fetch_calendar_async()
            except Exception as e:
                self.log(f"News filter initialization error: {e}", "WARN")

    @property
    def known_positions(self):
        return self.order_manager.tracked_positions

    @property
    def active_be_locked(self):
        return self.order_manager.active_be_locked

    @property
    def last_exit_m5_bar_time(self):
        return self.order_manager.last_exit_m5_bar_time

    @last_exit_m5_bar_time.setter
    def last_exit_m5_bar_time(self, val):
        self.order_manager.last_exit_m5_bar_time = val

    def get_filling_mode(self, symbol: str) -> int:
        """Determines the appropriate order filling mode supported by the broker for the symbol."""
        return self.order_manager.get_filling_mode(symbol)

    def log(self, message: str, level: str = "INFO"):
        """Logs event with timestamp and persists to rotating file."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] [{level}] {message}")
        if len(self.logs) > 7:
            self.logs.pop(0)
        # Persistent rotating log entry
        file_logger.info(f"[{level}] {message}")

    def setup(self) -> bool:
        """Initializes connection to MT5 and verifies XAUUSDm."""
        self.log(f"Connecting to MT5 for {self.symbol} scalping...", "INFO")
        if not self.connector.initialize():
            self.log("Failed to connect to MT5.", "ERROR")
            return False

        valid = self.connector.verify_symbol(self.symbol)
        if not valid:
            self.log(f"Symbol {self.symbol} could not be verified on MT5.", "ERROR")
            return False

        # Recover state of any already open Gold positions using unified tracker
        self.order_manager.hydrate_active_positions(self.symbol)

        self.log(f"Gold Scalper ready! Symbol: {self.symbol} | Magic: {self.magic} | Journal: SQLite Active", "SUCCESS")
        return True

    def get_gold_positions(self):
        """Retrieves active positions placed by this Gold Scalper."""
        return self.order_manager.get_gold_positions()

    def manage_gold_positions(self, atr_val: float, current_m5_bar_time: int = 0):
        """Manages Closed Trade Detection, Partial TP, Break-Even, and Dynamic ATR Trailing Stop."""
        active = self.get_gold_positions()
        return self.order_manager.manage_gold_positions(atr_val, current_m5_bar_time, positions=active)

    def execute_scalp(self, sig: str, atr_val: float):
        """Executes a validated Gold scalp order."""
        return self.order_manager.execute_scalp(sig, atr_val)

    def build_dashboard(self, analysis: dict, active_positions: list, cooldown_active: bool = False, bars_remaining: float = 0.0) -> Layout:
        """Renders live terminal dashboard for Gold Scalper."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", size=13),
            Layout(name="positions", size=5),
            Layout(name="logs", size=6),
        )

        acc = mt5.account_info()
        # Dual-Wave Session State Indicator
        dec_hour = hour + (now_utc.minute / 60.0)
        w1_start = getattr(config_gold, "WAVE_1_START_HOUR_UTC", 8.0)
        w1_end = getattr(config_gold, "WAVE_1_END_HOUR_UTC", 11.5)
        w2_start = getattr(config_gold, "WAVE_2_START_HOUR_UTC", 13.0)
        w2_end = getattr(config_gold, "WAVE_2_END_HOUR_UTC", 17.0)

        if w1_start <= dec_hour < w1_end:
            session_label = "🟢 LONDON OPEN (08:00 - 11:30 UTC)"
            session_style = "bold green"
        elif w1_end <= dec_hour < w2_start:
            session_label = "⏸️ MIDDAY LULL (11:30 - 13:00 UTC)"
            session_style = "bold yellow"
        elif w2_start <= dec_hour < w2_end:
            session_label = "🟢 NEW YORK OVERLAP (13:00 - 17:00 UTC)"
            session_style = "bold green"
        else:
            session_label = "🔴 OFF-HOURS (Asian / Late Night)"
            session_style = "bold red"

        # Header
        h_text = Text()
        h_text.append("[INSTITUTIONAL GOLD (XAUUSDm) ML SCALPER]", style="bold gold1")
        h_text.append(f"  |  Account: {acc.login if acc else 'N/A'}", style="bold yellow")
        h_text.append(f"  |  Session: {session_label}", style=session_style)
        h_text.append(f"  |  UTC: {now_utc.strftime('%H:%M:%S')}", style="bold white")
        layout["header"].update(Panel(h_text, style="gold1"))

        # Main Box
        layout["main"].split_row(
            Layout(name="account_box", ratio=1),
            Layout(name="market_box", ratio=1)
        )

        # Account Box
        acc_table = Table(box=None, expand=True)
        acc_table.add_column("Property", style="dim white")
        acc_table.add_column("Value", justify="right")
        acc_table.add_row("Balance / Equity", f"${acc.balance:.2f} / ${acc.equity:.2f}" if acc else "N/A")
        floating = (acc.equity - acc.balance) if acc else 0.0
        acc_table.add_row("Floating P&L", f"[{'bold green' if floating >= 0 else 'bold red'}]${floating:+.2f}[/]")
        acc_table.add_row("Free Margin", f"${acc.margin_free:.2f}" if acc else "N/A")
        tick_tmp = mt5.symbol_info_tick(self.symbol)
        needed_margin = (mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, self.symbol, 0.01, tick_tmp.ask) if tick_tmp else 20.65) or 20.65
        if acc and acc.margin_free < needed_margin:
            acc_table.add_row("0.01 Lot Margin", f"[bold red]${needed_margin:.2f} (SHORT ${needed_margin - acc.margin_free:.2f})[/bold red]")
        else:
            acc_table.add_row("0.01 Lot Margin", f"[bold green]${needed_margin:.2f} (Ready)[/bold green]")

        max_daily_loss = getattr(config_gold, "MAX_DAILY_LOSS_USD", 5.00)
        daily_loss_hit = False
        try:
            today_stats = self.journal.get_today_summary()
            j_pnl = today_stats.get("net_pnl", 0.0)
            j_wins = today_stats.get("wins", 0)
            j_losses = today_stats.get("losses", 0)
            j_wr = today_stats.get("win_rate", 0.0)
            daily_loss_hit = (j_pnl <= -max_daily_loss)
            acc_table.add_row("Today's Closed P&L", f"[{'bold green' if j_pnl >= 0 else 'bold red'}]${j_pnl:+.2f}[/] ({j_wins}W/{j_losses}L - {j_wr:.0f}%)")
        except Exception:
            acc_table.add_row("Today's Closed P&L", "$0.00 (0W/0L)")

        # Risk state display (unlimited trade count, capital drawdown protected)
        if daily_loss_hit:
            acc_table.add_row("Daily Equity Guard", "[bold red]LOCKED (-$5.00 Max Drawdown Reached)[/bold red]")
        else:
            acc_table.add_row("Daily Equity Guard", f"[bold green]OK (Max Loss: -${max_daily_loss:.2f} | Trades: Unlimited)[/bold green]")

        acc_table.add_row("Strategy Target", "[bold cyan]1:2 R:R (1.3x ATR SL / 2.6x ATR TP)[/bold cyan]")
        layout["account_box"].update(Panel(acc_table, title="[bold]Financial Health[/bold]", border_style="blue"))

        # Market Box
        metrics = analysis.get("metrics", {})
        sig = analysis.get("signal", "HOLD")
        conf = analysis.get("confidence", 0.0)
        grade = analysis.get("grade", "NONE")
        score = analysis.get("confluence_score", 0)
        setup_name = analysis.get("setup", "NONE")
        regime = analysis.get("regime", metrics.get("regime", "UNKNOWN"))
        levels = metrics.get("levels", {})
        ml_data = metrics.get("ml", {})
        p_win_val = ml_data.get("win_probability_pct", conf * 100.0)
        ev_val = ml_data.get("expected_value_r", 0.0)
        tick = mt5.symbol_info_tick(self.symbol)
        spread_pts = (tick.ask - tick.bid) / 0.001 if tick else 0

        m_table = Table(box=None, expand=True)
        m_table.add_column("Metric", style="dim white")
        m_table.add_column("Status", justify="right")
        m_table.add_row("Gold Spot Price", f"[bold yellow]${tick.bid:.2f} / ${tick.ask:.2f}[/bold yellow]" if tick else "N/A")
        m_table.add_row("Spread", f"{spread_pts:.0f} pts (${spread_pts*0.001:.2f})")
        m_table.add_row("Market Regime", f"[bold cyan]{regime}[/bold cyan]")
        m_table.add_row("Asian Range", f"${levels.get('asian_low', 0):.2f} - ${levels.get('asian_high', 0):.2f}")
        m_table.add_row("Volume Ratio", f"{metrics.get('vol_ratio', 1.0):.2f}x (SMA 20)")
        m_table.add_row("CHOP / ADX", f"CHOP: {metrics.get('chop', 0.0):.1f} | ADX: {metrics.get('adx', 0.0):.1f}")
        cd_display = "[bold green]READY[/bold green]" if not cooldown_active else f"[bold yellow]WAITING ({bars_remaining:.0f} M5 Bar)[/bold yellow]"
        m_table.add_row("Exit Cooldown", cd_display)
        cb_display = "[bold red]PAUSED (3 Losses)[/bold red]" if getattr(self, "circuit_breaker_active", False) else "[bold green]CLEAR[/bold green]"
        m_table.add_row("Circuit Breaker", cb_display)
        sig_col = "bold green" if sig == "BUY" else ("bold red" if sig == "SELL" else "bold yellow")
        m_table.add_row("Multi-Strat Setup", f"[bold magenta]{setup_name}[/bold magenta]")
        ev_col = "bold green" if ev_val >= 0.15 else ("bold yellow" if ev_val >= 0 else "dim red")
        m_table.add_row("ML Win Prob / EV", f"P: [bold white]{p_win_val:.1f}%[/bold white] | EV: [{ev_col}]{ev_val:+.2f}R[/]")
        m_table.add_row("Confluence Signal", f"[{sig_col}]{sig}[/] [[bold white]{grade}[/bold white]] ({score}/100 pts)")
        layout["market_box"].update(Panel(m_table, title="[bold]Institutional Multi-Strategy Confluence[/bold]", border_style="gold1"))

        # Positions
        pos_table = Table(expand=True)
        pos_table.add_column("Ticket", justify="center")
        pos_table.add_column("Type", justify="center")
        pos_table.add_column("Lot", justify="center")
        pos_table.add_column("Open", justify="right")
        pos_table.add_column("SL", justify="right")
        pos_table.add_column("TP", justify="right")
        pos_table.add_column("P&L ($)", justify="right")

        if active_positions:
            for p in active_positions:
                pt = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
                profit = getattr(p, "profit", 0.0) or 0.0
                col = "bold green" if profit >= 0 else "bold red"
                pos_table.add_row(str(p.ticket), pt, f"{p.volume:.2f}", f"${p.price_open:.2f}", f"${p.sl:.2f}", f"${p.tp:.2f}", f"[{col}]${profit:+.2f}[/]")
        else:
            pos_table.add_row("-", "NO OPEN GOLD POSITIONS", "-", "-", "-", "-", "$0.00")
        layout["positions"].update(Panel(pos_table, title="[bold]Active Gold Trades[/bold]", border_style="green"))

        # Logs
        log_text = "\n".join(self.logs) if self.logs else "Monitoring Gold market structure..."
        layout["logs"].update(Panel(log_text, title="[bold]Execution Log[/bold]", border_style="yellow"))

        return layout

    def start(self):
        """Main Gold Scalper loop."""
        if not self.setup():
            return

        self.running = True
        self.log(f"Gold Scalper live. Monitoring XAUUSDm on M5 with M1/H1 confirmation...", "SUCCESS")

        try:
            with Live(console=console, refresh_per_second=2, screen=False) as live:
                while self.running:
                    # 0. Self-Healing Connection Health Check & Terminal Auto-Recovery
                    if not self.connector.ensure_connection():
                        self.log("⚠️ MT5 connection drop detected. Auto-reconnecting to Exness...", "WARN")
                        time.sleep(3)
                        continue

                    # 1. Fetch data: M5 primary, H1 macro (220 bars for EMA 50/200), M1 micro-structure
                    m5_rates = self.connector.get_rates(self.symbol, config_gold.TIMEFRAME, count=100)
                    h1_rates = self.connector.get_rates(self.symbol, config_gold.HIGHER_TIMEFRAME, count=220)
                    m1_rates = self.connector.get_rates(self.symbol, config_gold.SCALP_TIMEFRAME, count=30)

                    if m5_rates is None or len(m5_rates) == 0:
                        self.log("⚠️ M5 data feed unavailable. Checking MT5 terminal link...", "WARN")
                        self.connector.ensure_connection()
                        time.sleep(2)
                        continue

                    current_m5_bar_time = m5_rates[-1]["time"] if m5_rates is not None and len(m5_rates) > 0 else 0

                    # 2. Run analysis with M1 confirmation
                    analysis = self.strategy.analyze(m5_rates, h1_rates, m1_rates)
                    sig = analysis.get("signal", "HOLD")
                    metrics = analysis.get("metrics", {})
                    atr_val = metrics.get("atr", 2.50)

                    # 3. Active position management (Partial TP, BE, Trailing Stop, Exit Logging)
                    self.manage_gold_positions(atr_val, current_m5_bar_time)
                    active_positions = self.get_gold_positions()

                    # 4. Check 1 Full New M5 Bar Cooldown
                    cooldown_active = False
                    bars_remaining = 0.0
                    cooldown_bars = getattr(config_gold, "BAR_COOLDOWN_M5_COUNT", 1)
                    if self.last_exit_m5_bar_time > 0 and current_m5_bar_time > 0:
                        bars_elapsed = (current_m5_bar_time - self.last_exit_m5_bar_time) / 300.0
                        needed = (cooldown_bars + 1)
                        if bars_elapsed < needed:
                            cooldown_active = True
                            bars_remaining = needed - bars_elapsed

                    # 5. Consecutive Loss Circuit Breaker Check
                    loss_limit = getattr(config_gold, "CONSECUTIVE_LOSS_LIMIT", 3)
                    cooling_bars = getattr(config_gold, "CONSECUTIVE_LOSS_COOLDOWN_BARS", 6)
                    if not self.circuit_breaker_active:
                        try:
                            rows = self.journal._execute(
                                "SELECT outcome FROM trades WHERE symbol = ? AND exit_time IS NOT NULL ORDER BY id DESC LIMIT ?",
                                (self.symbol, loss_limit),
                                fetch=True,
                                fetchall=True
                            )
                            if rows and len(rows) >= loss_limit and all(r[0] == "LOSS" for r in rows):
                                self.circuit_breaker_active = True
                                self.circuit_breaker_until_bar = current_m5_bar_time + (cooling_bars * 300)
                                self.log(f"⚠️ Circuit Breaker: {loss_limit} consecutive losses hit. Pausing for {cooling_bars} bars.", "WARN")
                        except Exception:
                            pass
                    else:
                        if current_m5_bar_time >= self.circuit_breaker_until_bar:
                            self.circuit_breaker_active = False
                            self.log("✅ Circuit Breaker cooling period finished. Resuming scalp executions.", "SUCCESS")

                    # 6. Check Daily Equity Drawdown Limit (Uncapped trades, but equity protected)
                    daily_drawdown_locked = False
                    max_loss = getattr(config_gold, "MAX_DAILY_LOSS_USD", 5.00)
                    try:
                        today_stats = self.journal.get_today_summary()
                        if today_stats.get("net_pnl", 0.0) <= -max_loss:
                            daily_drawdown_locked = True
                    except Exception:
                        pass

                    # 7. Check High-Impact News Blackout
                    news_blackout = False
                    news_reason = ""
                    if self.news_filter and getattr(config_gold, "NEWS_FILTER_ENABLED", True):
                        self.news_filter.fetch_calendar_async()
                        is_blocked, ev_title, _ = self.news_filter.is_news_blackout(self.symbol)
                        if is_blocked:
                            news_blackout = True
                            news_reason = ev_title

                    # 8. Execute if valid signal, no active trades, and guards pass
                    if sig in ["BUY", "SELL"] and len(active_positions) < config_gold.MAX_OPEN_POSITIONS:
                        if cooldown_active:
                            self.log("⏸️ Cooldown Guard: Waiting for 1 full new completed M5 candle after exit.", "INFO")
                        elif self.circuit_breaker_active:
                            self.log(f"⏸️ Circuit Breaker: Paused due to {loss_limit} consecutive losses.", "WARN")
                        elif daily_drawdown_locked:
                            self.log(f"🛑 Equity Guard: Daily loss limit hit (-${max_loss:.2f}). Trading paused for today.", "WARN")
                        elif news_blackout:
                            self.log(f"📰 News Guard: Trading halted due to High-Impact News: {news_reason}", "WARN")
                        else:
                            # Re-verify position count to prevent race conditions
                            fresh_positions = self.get_gold_positions()
                            if len(fresh_positions) < config_gold.MAX_OPEN_POSITIONS:
                                self.execute_scalp(sig, atr_val)

                    # 9. Render dashboard
                    dashboard = self.build_dashboard(analysis, active_positions, cooldown_active, bars_remaining)
                    live.update(dashboard)

                    time.sleep(3)

        except KeyboardInterrupt:
            self.log("Gold Scalper stopped by user (Ctrl+C).", "INFO")
        finally:
            self.connector.shutdown()
            console.print("[bold green]Gold Scalper shut down safely.[/bold green]")


if __name__ == "__main__":
    bot = GoldScalperBot()
    bot.start()
