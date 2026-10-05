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

# Add parent and crypto_forex_bot directories to path
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRYPTO_DIR = os.path.join(PARENT_DIR, "crypto_forex_bot")
for d in [PARENT_DIR, CRYPTO_DIR]:
    if d not in sys.path:
        sys.path.append(d)

from gold_scalper import config_gold
from gold_scalper.strategy_gold import GoldScalperStrategy

from crypto_forex_bot.mt5_connector import MT5Connector
from crypto_forex_bot.notifier import DiscordNotifier

console = Console()


class GoldScalperBot:
    """Independent Gold Scalping Bot with dedicated risk and position tracking."""

    def __init__(self):
        self.connector = MT5Connector()
        self.strategy = GoldScalperStrategy()
        self.notifier = DiscordNotifier(config_gold.DISCORD_WEBHOOK_URL)
        self.running = False
        self.logs = []
        self.symbol = config_gold.SYMBOL
        self.magic = config_gold.MAGIC_NUMBER
        self.active_be_locked = set()

    def log(self, message: str, level: str = "INFO"):
        """Logs event with timestamp."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] [{level}] {message}")
        if len(self.logs) > 7:
            self.logs.pop(0)

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

        self.log(f"Gold Scalper ready! Symbol: {self.symbol} | Magic: {self.magic} | Session: 08:00-16:00 UTC", "SUCCESS")
        return True

    def get_gold_positions(self):
        """Retrieves active positions placed by this Gold Scalper."""
        all_pos = mt5.positions_get(symbol=self.symbol)
        if not all_pos:
            return []
        return [p for p in all_pos if p.magic == self.magic]

    def manage_gold_positions(self, atr_val: float):
        """Manages Partial TP and Break-Even locking for active Gold trades."""
        positions = self.get_gold_positions()
        if not positions or atr_val <= 0:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return

        info = mt5.symbol_info(self.symbol)
        digits = info.digits if info else 3
        min_vol = info.volume_min if info else 0.01

        for p in positions:
            entry = p.price_open
            ticket = p.ticket
            cur_sl = p.sl
            cur_vol = p.volume
            p_type = p.type

            target_tp1 = atr_val * config_gold.PARTIAL_TP_RATIO
            be_buffer = 0.10  # 10 cents on Gold

            if p_type == mt5.ORDER_TYPE_BUY:
                profit_dist = tick.bid - entry
                if profit_dist >= target_tp1 and ticket not in self.active_be_locked:
                    # 1. Partial close 50% lot if volume >= 0.02
                    if cur_vol >= (min_vol * 2):
                        close_vol = round(cur_vol / 2.0, 2)
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "position": ticket,
                            "symbol": self.symbol,
                            "volume": close_vol,
                            "type": mt5.ORDER_TYPE_SELL,
                            "price": tick.bid,
                            "deviation": 20,
                            "magic": self.magic,
                            "comment": "Gold Scalp TP1 Partial",
                            "type_filling": mt5.ORDER_FILLING_IOC
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            self.log(f"🎯 TP1 hit on Gold #{ticket}: Closed {close_vol} lots @ {tick.bid:.2f}", "TRADE")

                    # 2. Lock Break-Even
                    new_sl = round(entry + be_buffer, digits)
                    if new_sl > cur_sl:
                        mod_req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": self.symbol,
                            "sl": new_sl,
                            "tp": p.tp
                        }
                        res = mt5.order_send(mod_req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            self.active_be_locked.add(ticket)
                            self.log(f"🛡️ Risk-Free Lock: SL moved to Break-Even ({new_sl:.2f}) on Gold #{ticket}", "TRADE")

            elif p_type == mt5.ORDER_TYPE_SELL:
                profit_dist = entry - tick.ask
                if profit_dist >= target_tp1 and ticket not in self.active_be_locked:
                    if cur_vol >= (min_vol * 2):
                        close_vol = round(cur_vol / 2.0, 2)
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "position": ticket,
                            "symbol": self.symbol,
                            "volume": close_vol,
                            "type": mt5.ORDER_TYPE_BUY,
                            "price": tick.ask,
                            "deviation": 20,
                            "magic": self.magic,
                            "comment": "Gold Scalp TP1 Partial",
                            "type_filling": mt5.ORDER_FILLING_IOC
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            self.log(f"🎯 TP1 hit on Gold #{ticket}: Closed {close_vol} lots @ {tick.ask:.2f}", "TRADE")

                    new_sl = round(entry - be_buffer, digits)
                    if cur_sl == 0 or new_sl < cur_sl:
                        mod_req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": ticket,
                            "symbol": self.symbol,
                            "sl": new_sl,
                            "tp": p.tp
                        }
                        res = mt5.order_send(mod_req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            self.active_be_locked.add(ticket)
                            self.log(f"🛡️ Risk-Free Lock: SL moved to Break-Even ({new_sl:.2f}) on Gold #{ticket}", "TRADE")

    def execute_scalp(self, sig: str, atr_val: float):
        """Executes a validated Gold scalp order."""
        if len(self.get_gold_positions()) >= config_gold.MAX_OPEN_POSITIONS:
            return

        tick = mt5.symbol_info_tick(self.symbol)
        info = mt5.symbol_info(self.symbol)
        if not tick or not info:
            return

        digits = info.digits
        entry = tick.ask if sig == "BUY" else tick.bid
        stop_dist = atr_val * config_gold.ATR_SL_MULTIPLIER

        sl = round(entry - stop_dist if sig == "BUY" else entry + stop_dist, digits)
        tp = round(entry + (stop_dist * config_gold.ATR_TP_MULTIPLIER) if sig == "BUY" else entry - (stop_dist * config_gold.ATR_TP_MULTIPLIER), digits)

        # Lot size: 0.01 base or risk-based
        acc = mt5.account_info()
        equity = acc.equity if acc else 30.0
        risk_usd = equity * (config_gold.RISK_PER_TRADE_PERCENT / 100.0)
        # 1 lot of XAUUSD = 100 oz. $1.00 move = $100 per lot.
        loss_per_lot = stop_dist * 100.0
        calc_lots = round(risk_usd / max(loss_per_lot, 1e-9), 2)
        lots = max(info.volume_min, min(info.volume_max, calc_lots if calc_lots >= info.volume_min else info.volume_min))

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": lots,
            "type": mt5.ORDER_TYPE_BUY if sig == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": entry,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": self.magic,
            "comment": "Gold Institutional Scalp",
            "type_filling": mt5.ORDER_FILLING_IOC
        }

        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            self.log(f"⚡ EXECUTED {sig} on Gold #{res.order} | Lots: {lots:.2f} @ {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", "TRADE")
            if self.notifier.enabled:
                self.notifier.send(f"⚡ [XAUUSDm] {sig} Scalp Executed #{res.order}\nLots: {lots:.2f} @ {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        else:
            err = res.comment if res else str(mt5.last_error())
            self.log(f"Execution failed on Gold: {err}", "ERROR")

    def build_dashboard(self, analysis: dict, active_positions: list) -> Layout:
        """Renders live terminal dashboard for Gold Scalper."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", size=10),
            Layout(name="positions", size=6),
            Layout(name="logs", size=8),
        )

        acc = mt5.account_info()
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        session_active = (7 <= hour < 18)

        # Header
        h_text = Text()
        h_text.append("[INSTITUTIONAL GOLD (XAUUSDm) SCALPER ENGINE]", style="bold gold1")
        h_text.append(f"  |  Account: {acc.login if acc else 'N/A'}", style="bold yellow")
        h_text.append(f"  |  Session: {'🟢 ACTIVE (London/NY)' if session_active else '🔴 OFF-HOURS (Asian)'}", style="bold green" if session_active else "bold red")
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
        acc_table.add_row("Active Scalper Target", "[bold cyan]1.0x ATR (Partial) / 2.0x ATR (Full)[/bold cyan]")
        layout["account_box"].update(Panel(acc_table, title="[bold]Financial Health[/bold]", border_style="blue"))

        # Market Box
        metrics = analysis.get("metrics", {})
        sig = analysis.get("signal", "HOLD")
        conf = analysis.get("confidence", 0.0)
        tick = mt5.symbol_info_tick(self.symbol)
        spread_pts = (tick.ask - tick.bid) / 0.001 if tick else 0

        m_table = Table(box=None, expand=True)
        m_table.add_column("Metric", style="dim white")
        m_table.add_column("Status", justify="right")
        m_table.add_row("Gold Spot Price", f"[bold yellow]${tick.bid:.2f} / ${tick.ask:.2f}[/bold yellow]" if tick else "N/A")
        m_table.add_row("Spread", f"{spread_pts:.0f} pts (${spread_pts*0.001:.2f})")
        m_table.add_row("M5 / H1 Trend", f"{metrics.get('close', 0.0)} | H1: [bold]{metrics.get('h1_trend', 'N/A')}[/bold]")
        m_table.add_row("CHOP / ADX", f"CHOP: {metrics.get('chop', 0.0):.1f} | ADX: {metrics.get('adx', 0.0):.1f}")
        m_table.add_row("M5 ATR Volatility", f"${metrics.get('atr', 0.0):.2f}")
        m_table.add_row("Scalp Signal", f"[{'bold green' if sig == 'BUY' else ('bold red' if sig == 'SELL' else 'bold yellow')}]{sig}[/] ({conf*100:.0f}%)")
        layout["market_box"].update(Panel(m_table, title="[bold]Gold Scalper Edge & Confluence[/bold]", border_style="gold1"))

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
        self.log(f"Gold Scalper live. Monitoring XAUUSDm on M5 with H1 confirmation...", "SUCCESS")

        try:
            with Live(console=console, refresh_per_second=2, screen=False) as live:
                while self.running:
                    # 1. Fetch data
                    m5_rates = self.connector.get_rates(self.symbol, config_gold.TIMEFRAME, count=100)
                    h1_rates = self.connector.get_rates(self.symbol, config_gold.HIGHER_TIMEFRAME, count=50)

                    # 2. Run analysis
                    analysis = self.strategy.analyze(m5_rates, h1_rates)
                    sig = analysis.get("signal", "HOLD")
                    metrics = analysis.get("metrics", {})
                    atr_val = metrics.get("atr", 2.50)

                    # 3. Active position management (Partial TP & BE)
                    self.manage_gold_positions(atr_val)
                    active_positions = self.get_gold_positions()

                    # 4. Execute if valid signal and no active trades
                    if sig in ["BUY", "SELL"] and len(active_positions) < config_gold.MAX_OPEN_POSITIONS:
                        self.execute_scalp(sig, atr_val)

                    # 5. Render dashboard
                    dashboard = self.build_dashboard(analysis, active_positions)
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
