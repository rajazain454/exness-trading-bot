import logging
import requests
import queue
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import config

logger = logging.getLogger("Notifier")

class DiscordNotifier:
    """Sends real-time embeds and performance recaps to Discord asynchronously."""

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or config.DISCORD_WEBHOOK_URL
        self.enabled = bool(self.webhook_url and self.webhook_url.startswith("https://discord.com/api/webhooks/"))
        self._queue = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        self._worker_thread = None
        if self.enabled:
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True, name="DiscordWorker")
            self._worker_thread.start()

    def _process_queue(self):
        """Background worker thread draining the notification queue."""
        while not self._stop_event.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
                try:
                    res = requests.post(self.webhook_url, json=payload, timeout=6)
                    if res.status_code not in [200, 204]:
                        logger.warning(f"Discord returned HTTP status {res.status_code}")
                except Exception as e:
                    logger.warning(f"Failed to deliver Discord notification: {e}")
                finally:
                    self._queue.task_done()
            except queue.Empty:
                continue

    def send_embed(self, title: str, description: str, color: int, fields: Optional[list] = None) -> bool:
        """Enqueues a rich Discord embed asynchronously without blocking the trading loop."""
        if not self.enabled:
            return False

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Exness Algorithmic Trading Suite"}
        }

        if fields:
            embed["fields"] = fields

        payload = {
            "username": "Exness Trading Bot",
            "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/4/42/Exness_logo_2024.png",
            "embeds": [embed]
        }

        try:
            self._queue.put_nowait(payload)
            return True
        except queue.Full:
            logger.warning("Discord notification queue is full (100 items). Dropping message.")
            return False

    def shutdown(self, timeout: float = 2.0):
        """Flushes remaining notifications and terminates worker."""
        if not self.enabled or not self._worker_thread:
            return
        self._stop_event.set()
        try:
            self._worker_thread.join(timeout=timeout)
        except Exception:
            pass

    def notify_trade_opened(self, symbol: str, signal: str, ticket: int, entry: float, sl: float, tp: float, lot: float, balance: float):
        """Alerts when a new position is executed."""
        color = 0x2ECC71 if signal == "BUY" else 0xE74C3C
        fields = [
            {"name": "Symbol", "value": f"`{symbol}`", "inline": True},
            {"name": "Action", "value": f"**{signal}**", "inline": True},
            {"name": "Ticket #", "value": str(ticket), "inline": True},
            {"name": "Lot Size", "value": f"`{lot}`", "inline": True},
            {"name": "Entry Price", "value": f"`{entry:.5f}`", "inline": True},
            {"name": "Stop Loss", "value": f"`{sl:.5f}`", "inline": True},
            {"name": "Take Profit", "value": f"`{tp:.5f}`", "inline": True},
            {"name": "Account Balance", "value": f"`${balance:.2f}`", "inline": True}
        ]
        self.send_embed(
            title=f"⚡ NEW TRADE OPENED: {signal} {symbol}",
            description="Algorithmic confluence trigger verified and executed on Exness.",
            color=color,
            fields=fields
        )

    def notify_partial_tp_locked(self, symbol: str, ticket: int, closed_lot: float, remaining_lot: float, pnl_usd: float, new_sl: float):
        """Alerts when partial profit is banked and remaining position continues risk-free."""
        fields = [
            {"name": "Ticket #", "value": str(ticket), "inline": True},
            {"name": "Closed Volume", "value": f"`{closed_lot:.2f}` Lot", "inline": True},
            {"name": "Banked Profit", "value": f"**+${pnl_usd:.2f}**", "inline": True},
            {"name": "Remaining Runner", "value": f"`{remaining_lot:.2f}` Lot", "inline": True},
            {"name": "Secured SL", "value": f"`{new_sl:.5f}`", "inline": True}
        ]
        self.send_embed(
            title="🎯 PARTIAL TAKE-PROFIT BANKED",
            description=f"Scaled out 50% of position on `{symbol}` at TP1. Remaining volume now running risk-free towards TP2 with Trailing Stop!",
            color=0x2ECC71,
            fields=fields
        )

    def notify_breakeven_locked(self, symbol: str, ticket: int, order_type: str, new_sl: float):
        """Alerts when Stop Loss is moved to break-even."""
        fields = [
            {"name": "Ticket #", "value": str(ticket), "inline": True},
            {"name": "Position Type", "value": order_type, "inline": True},
            {"name": "Protected SL", "value": f"`{new_sl:.5f}`", "inline": True}
        ]
        self.send_embed(
            title="🛡️ BREAK-EVEN TRIGGERED (RISK-FREE TRADE)",
            description=f"Position #{ticket} on `{symbol}` has gained sufficient profit. Stop Loss moved to Entry + 1 pip.",
            color=0x3498DB,
            fields=fields
        )

    def notify_trailing_stop_updated(self, symbol: str, ticket: int, new_sl: float):
        """Alerts when Stop Loss is trailed higher."""
        fields = [
            {"name": "Ticket #", "value": str(ticket), "inline": True},
            {"name": "New Trailing SL", "value": f"`{new_sl:.5f}`", "inline": True}
        ]
        self.send_embed(
            title="📈 TRAILING STOP UPDATED",
            description=f"Trailing Stop advanced on `{symbol}` to lock in additional profit.",
            color=0x9B59B6,
            fields=fields
        )

    def notify_trade_closed(self, ticket: int, symbol: str, pnl_usd: float, balance: float, reason: str = "Exit Target Hit"):
        """Alerts when a position closes with final PnL."""
        is_win = pnl_usd >= 0
        color = 0x2ECC71 if is_win else 0xE74C3C
        emoji = "🎯" if is_win else "🛑"
        status_text = "WIN" if is_win else "LOSS"

        fields = [
            {"name": "Outcome", "value": f"**{status_text}**", "inline": True},
            {"name": "Profit / Loss", "value": f"**{'+' if is_win else ''}${pnl_usd:.2f}**", "inline": True},
            {"name": "New Balance", "value": f"`${balance:.2f}`", "inline": True},
            {"name": "Close Reason", "value": reason, "inline": False}
        ]
        self.send_embed(
            title=f"{emoji} TRADE CLOSED: #{ticket} ({symbol})",
            description="Position finalized on Exness platform.",
            color=color,
            fields=fields
        )

    def notify_daily_summary(self, summary: Dict[str, Any], balance: float, equity: float):
        """Dispatches End-of-Day performance recap to Discord."""
        net = summary.get("net_pnl", 0.0)
        color = 0x2ECC71 if net >= 0 else 0xE74C3C
        fields = [
            {"name": "Total Trades", "value": str(summary.get("total", 0)), "inline": True},
            {"name": "Win / Loss", "value": f"{summary.get('wins', 0)}W / {summary.get('losses', 0)}L", "inline": True},
            {"name": "Win Rate", "value": f"{summary.get('win_rate', 0.0)}%", "inline": True},
            {"name": "Net P&L", "value": f"**{'+' if net >= 0 else ''}${net:.2f}**", "inline": True},
            {"name": "Closing Balance", "value": f"${balance:.2f}", "inline": True},
            {"name": "Closing Equity", "value": f"${equity:.2f}", "inline": True},
        ]
        self.send_embed(
            title="🌙 DAILY TRADING PERFORMANCE DIGEST",
            description=f"Performance summary for {datetime.utcnow().strftime('%Y-%m-%d')} across active Exness sessions.",
            color=color,
            fields=fields
        )

    def notify_cooldown_activated(self, losses_count: int, cooldown_hours: int):
        """Alerts when consecutive loss cooldown is triggered."""
        fields = [
            {"name": "Consecutive Losses", "value": str(losses_count), "inline": True},
            {"name": "Cooldown Duration", "value": f"{cooldown_hours} Hours", "inline": True}
        ]
        self.send_embed(
            title="🛑 CONSECUTIVE LOSS COOLDOWN ACTIVATED",
            description="Bot has paused new entries to let erratic market dynamics settle and protect account capital.",
            color=0xE67E22,
            fields=fields
        )

    def notify_heartbeat(self, account: int, server: str, balance: float, uptime_str: str):
        """Sends an operational heartbeat health check."""
        fields = [
            {"name": "Account", "value": str(account), "inline": True},
            {"name": "Server", "value": server, "inline": True},
            {"name": "Current Balance", "value": f"${balance:.2f}", "inline": True},
            {"name": "Status", "value": "🟢 All Systems Operational", "inline": True},
            {"name": "Uptime", "value": uptime_str, "inline": True}
        ]
        self.send_embed(
            title="💓 BOT OPERATIONAL HEARTBEAT",
            description="Exness background trading engine and risk checks running smoothly.",
            color=0x3498DB,
            fields=fields
        )

    def notify_connection_restored(self, server: str, account: int):
        """Alerts when auto-recovery restores broker connection."""
        self.send_embed(
            title="🔄 CONNECTION RESTORED",
            description=f"Auto-recovery successfully re-established connection to {server} (#{account}).",
            color=0x2ECC71,
            fields=[]
        )
