import logging
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import MetaTrader5 as mt5
import config
from notifier import DiscordNotifier
from journal import TradeJournal
from crypto_forex_bot.base_order_manager import BaseOrderManager

logger = logging.getLogger("OrderManager")

class OrderManager(BaseOrderManager):
    """
    Manages order execution, millisecond latency & slippage monitoring,
    limit pullback entries, smart partial profit-taking, break-even locks,
    trailing stops, and Friday market close protection.
    Inherits core broker primitives and state tracking from BaseOrderManager.
    """

    def __init__(self, connector, risk_manager=None):
        super().__init__(
            connector=connector,
            magic_number=config.MAGIC_NUMBER,
            notifier=DiscordNotifier(),
            journal=TradeJournal(),
            risk_manager=risk_manager,
            deviation_points=config.DEVIATION_POINTS,
        )
        # Hydrate existing positions across restarts
        self.hydrate_active_positions()

    def cancel_expired_pending_orders(self) -> int:
        """
        Cancels pending limit orders that have exceeded PENDING_ORDER_EXPIRY_MINS.
        Prevents stale limit orders from sitting on the book indefinitely.
        """
        pending_orders = self.get_pending_orders()
        if not pending_orders:
            return 0

        cancelled_count = 0
        now_ts = datetime.now(timezone.utc).timestamp()
        expiry_seconds = getattr(config, "PENDING_ORDER_EXPIRY_MINS", 15) * 60

        for order in pending_orders:
            order_time = getattr(order, "time_setup", 0)
            if order_time <= 0:
                continue
            age_secs = now_ts - order_time
            if age_secs >= expiry_seconds:
                request = {
                    "action": mt5.TRADE_ACTION_REMOVE,
                    "order": order.ticket,
                    "magic": self.magic_number
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    age_mins = age_secs / 60.0
                    logger.info(f"Cancelled expired pending order #{order.ticket} on {order.symbol} (Age: {age_mins:.1f}m > {config.PENDING_ORDER_EXPIRY_MINS}m)")
                    cancelled_count += 1
                else:
                    err = result.comment if result else mt5.last_error()
                    logger.warning(f"Failed to cancel pending order #{order.ticket}: {err}")

        return cancelled_count

    def open_position(self, symbol: str, signal: str, trade_params: Dict[str, float]) -> Optional[int]:
        """
        Executes order (Market or Limit Pullback) with precision latency & slippage tracking.
        Logs metrics to SQLite journal and dispatches Discord notification.
        """
        tick = self.connector.get_symbol_tick(symbol)
        if not tick:
            logger.error("Could not fetch tick to execute trade.")
            return None

        pip_size = self.connector.get_pip_size(symbol)
        filling = self.get_filling_mode(symbol)

        # Check entry mode: Market vs Limit Pullback
        if config.ENTRY_ORDER_TYPE == "LIMIT_PULLBACK":
            atr_val = trade_params.get("atr", 0.0)
            is_crypto = any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"])
            if atr_val > 0:
                limit_offset = 0.10 * atr_val
            elif is_crypto:
                spread_dist = tick.ask - tick.bid
                limit_offset = max(spread_dist * 1.5, 10.0 * pip_size)
            else:
                limit_offset = config.LIMIT_PULLBACK_OFFSET_PIPS * pip_size

            order_type = mt5.ORDER_TYPE_BUY_LIMIT if signal == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            req_price = round((tick.ask - limit_offset) if signal == "BUY" else (tick.bid + limit_offset), 5)
            action = mt5.TRADE_ACTION_PENDING
        else:
            order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
            req_price = tick.ask if signal == "BUY" else tick.bid
            action = mt5.TRADE_ACTION_DEAL

        request = {
            "action": action,
            "symbol": symbol,
            "volume": float(trade_params["lot"]),
            "type": order_type,
            "price": float(req_price),
            "sl": float(trade_params["sl"]),
            "tp": float(trade_params["tp"]),
            "deviation": int(config.DEVIATION_POINTS),
            "magic": self.magic_number,
            "comment": f"Exness_{config.ENTRY_ORDER_TYPE}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        # Measure roundtrip latency
        t_start = time.perf_counter()
        result = mt5.order_send(request)
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = result.comment if result else mt5.last_error()
            logger.error(f"Order rejected on Exness: {err}")
            return None

        ticket = result.order
        executed_price = result.price if result.price > 0 else req_price
        slippage_pips = round(abs(executed_price - req_price) / pip_size, 2)

        if slippage_pips >= config.MAX_SLIPPAGE_WARNING_PIPS:
            logger.warning(f"High slippage detected: {slippage_pips} pips on {symbol} (Latency: {latency_ms:.1f}ms)")

        logger.info(f"Order #{ticket} executed ({config.ENTRY_ORDER_TYPE}) on Exness! Latency: {latency_ms:.1f}ms | Slippage: {slippage_pips}p")

        # Unified tracking and journaling in BaseOrderManager
        self.record_new_position(
            ticket=ticket,
            symbol=symbol,
            signal=signal,
            lot=float(trade_params["lot"]),
            entry_price=float(executed_price),
            sl=float(trade_params["sl"]),
            tp=float(trade_params["tp"]),
            latency_ms=latency_ms,
            slippage_pips=slippage_pips
        )

        return ticket

    def manage_trailing_and_breakeven(self, symbol: str):
        """Monitors active trades for Smart Partial TP, Break-Even, and Trailing Stops."""
        positions = self.get_bot_positions(symbol)
        active_tickets = {p.ticket for p in positions}

        closed_tickets = [t for t in self.tracked_positions if t not in active_tickets]
        for t in closed_tickets:
            self._handle_position_closed(t)

        if not positions:
            return

        tick = self.connector.get_symbol_tick(symbol)
        if not tick:
            return

        pip_size = self.connector.get_pip_size(symbol)
        is_crypto = any(c in symbol for c in ["BTC", "ETH", "SOL", "XRP"])

        for pos in positions:
            ticket = pos.ticket
            pos_meta = self.tracked_positions.get(ticket, {})

            # Derive dynamic targets from actual initial stop distance if available
            risk_dist = abs(pos.price_open - pos.sl) if pos.sl > 0 else 0.0
            if risk_dist > 0:
                be_trigger = risk_dist * 0.50
                be_offset = risk_dist * 0.10
                trail_dist = risk_dist
                trail_step = risk_dist * 0.20
                partial_tp_dist = risk_dist * 0.80
            else:
                be_trigger = config.BREAKEVEN_TRIGGER_PIPS * pip_size
                be_offset = config.BREAKEVEN_OFFSET_PIPS * pip_size
                trail_dist = config.TRAILING_DISTANCE_PIPS * pip_size
                trail_step = config.TRAILING_STEP_PIPS * pip_size
                partial_tp_dist = config.PARTIAL_TP_PIPS * pip_size

            # BUY Position Management
            if pos.type == mt5.ORDER_TYPE_BUY:
                current_profit_distance = tick.bid - pos.price_open
                be_price = round(pos.price_open + be_offset, 5)

                if config.ENABLE_PARTIAL_TP and pos.volume >= 0.02 and not pos_meta.get("partial_closed"):
                    if current_profit_distance >= partial_tp_dist:
                        close_vol = round(pos.volume * config.PARTIAL_CLOSE_RATIO, 2)
                        if self.close_partial_position(pos, close_vol):
                            pos_meta["partial_closed"] = True
                            remaining_vol = round(pos.volume - close_vol, 2)
                            pips_banked = current_profit_distance / pip_size
                            pip_dollar_val = self.connector.get_pip_dollar_value(symbol, close_vol)
                            pnl_banked = round(pips_banked * pip_dollar_val, 2)

                            logger.info(f"[Partial-TP] Banked +${pnl_banked:.2f} on BUY #{ticket}. Remaining: {remaining_vol} lot.")
                            self.update_sl(pos, be_price)
                            self.notifier.notify_partial_tp_locked(symbol, ticket, close_vol, remaining_vol, pnl_banked, be_price)
                            continue

                if current_profit_distance >= be_trigger and not pos_meta.get("be_locked"):
                    if pos.sl < be_price:
                        if self.update_sl(pos, be_price):
                            pos_meta["be_locked"] = True
                            logger.info(f"[Break-Even] Locked on BUY #{ticket}. SL -> {be_price}")
                            self.notifier.notify_breakeven_locked(symbol, ticket, "BUY", be_price)
                            continue

                if config.TRAILING_STOP_ENABLED and current_profit_distance >= trail_dist:
                    target_sl = round(tick.bid - trail_dist, 5)
                    if target_sl > (pos.sl + trail_step):
                        if self.update_sl(pos, target_sl):
                            logger.info(f"[Trailing-Stop] Advanced on BUY #{ticket}. SL -> {target_sl}")
                            self.notifier.notify_trailing_stop_updated(symbol, ticket, target_sl)

            # SELL Position Management
            elif pos.type == mt5.ORDER_TYPE_SELL:
                current_profit_distance = pos.price_open - tick.ask
                be_price = round(pos.price_open - be_offset, 5)

                if config.ENABLE_PARTIAL_TP and pos.volume >= 0.02 and not pos_meta.get("partial_closed"):
                    if current_profit_distance >= partial_tp_dist:
                        close_vol = round(pos.volume * config.PARTIAL_CLOSE_RATIO, 2)
                        if self.close_partial_position(pos, close_vol):
                            pos_meta["partial_closed"] = True
                            remaining_vol = round(pos.volume - close_vol, 2)
                            pips_banked = current_profit_distance / pip_size
                            pip_dollar_val = self.connector.get_pip_dollar_value(symbol, close_vol)
                            pnl_banked = round(pips_banked * pip_dollar_val, 2)

                            logger.info(f"[Partial-TP] Banked +${pnl_banked:.2f} on SELL #{ticket}. Remaining: {remaining_vol} lot.")
                            self.update_sl(pos, be_price)
                            self.notifier.notify_partial_tp_locked(symbol, ticket, close_vol, remaining_vol, pnl_banked, be_price)
                            continue

                if current_profit_distance >= be_trigger and not pos_meta.get("be_locked"):
                    if pos.sl == 0.0 or pos.sl > be_price:
                        if self.update_sl(pos, be_price):
                            pos_meta["be_locked"] = True
                            logger.info(f"[Break-Even] Locked on SELL #{ticket}. SL -> {be_price}")
                            self.notifier.notify_breakeven_locked(symbol, ticket, "SELL", be_price)
                            continue

                if config.TRAILING_STOP_ENABLED and current_profit_distance >= trail_dist:
                    target_sl = round(tick.ask + trail_dist, 5)
                    if pos.sl == 0.0 or target_sl < (pos.sl - trail_step):
                        if self.update_sl(pos, target_sl):
                            logger.info(f"[Trailing-Stop] Advanced on SELL #{ticket}. SL -> {target_sl}")
                            self.notifier.notify_trailing_stop_updated(symbol, ticket, target_sl)

    def _handle_position_closed(self, ticket: int):
        """Fetches final deal profit from MT5, updates SQLite journal, and notifies Discord."""
        self.detect_and_handle_closed_positions()

    def check_friday_auto_close(self, symbols: Optional[List[str]] = None) -> bool:
        """Closes active Forex positions on Friday before weekend gap risk. Exempts 24/7 crypto."""
        if not config.FRIDAY_AUTO_CLOSE_ENABLED:
            return False

        now_utc = datetime.now(timezone.utc)
        if now_utc.weekday() == 4 and now_utc.hour >= config.FRIDAY_CUTOFF_HOUR_UTC:
            positions = self.get_bot_positions()
            # Filter to Forex/metal positions only; 24/7 crypto trades continuously
            forex_positions = [
                p for p in positions
                if not any(c in getattr(p, "symbol", "").upper() for c in ["BTC", "ETH", "SOL", "XRP"])
            ]
            if forex_positions:
                logger.info(f"Friday cutoff reached ({now_utc.hour:02d}:00 UTC). Auto-closing {len(forex_positions)} Forex positions (Crypto exempted).")
                for pos in forex_positions:
                    self.close_position(pos, reason="Friday Weekend Gap Protection")
                return True
        return False

