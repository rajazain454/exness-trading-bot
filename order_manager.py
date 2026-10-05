import logging
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import MetaTrader5 as mt5
import config
from notifier import DiscordNotifier
from journal import TradeJournal

logger = logging.getLogger("OrderManager")

class OrderManager:
    """
    Manages order execution, millisecond latency & slippage monitoring,
    limit pullback entries, smart partial profit-taking, break-even locks,
    trailing stops, and Friday market close protection.
    """

    def __init__(self, connector, risk_manager=None):
        self.connector = connector
        self.risk_manager = risk_manager
        self.notifier = DiscordNotifier()
        self.journal = TradeJournal()
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}

    def get_filling_mode(self, symbol: str) -> int:
        """Determines the appropriate order filling mode for the symbol."""
        info = mt5.symbol_info(symbol)
        if not info:
            return mt5.ORDER_FILLING_IOC

        filling_mode = info.filling_mode
        if filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        elif filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_IOC

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
            "magic": int(config.MAGIC_NUMBER),
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

        self.tracked_positions[ticket] = {
            "symbol": symbol,
            "signal": signal,
            "entry": float(executed_price),
            "lot": float(trade_params["lot"]),
            "sl": float(trade_params["sl"]),
            "tp": float(trade_params["tp"]),
            "be_locked": False,
            "partial_closed": False
        }

        # Log into SQLite Journal with latency and slippage
        self.journal.record_entry(
            ticket=ticket,
            symbol=symbol,
            signal=signal,
            lot=float(trade_params["lot"]),
            entry_price=float(executed_price),
            sl=float(trade_params["sl"]),
            tp=float(trade_params["tp"]),
            latency_ms=round(latency_ms, 1),
            slippage_pips=slippage_pips
        )

        acc = self.connector.get_account_summary()
        self.notifier.notify_trade_opened(
            symbol=symbol,
            signal=signal,
            ticket=ticket,
            entry=executed_price,
            sl=trade_params["sl"],
            tp=trade_params["tp"],
            lot=trade_params["lot"],
            balance=acc.get("balance", 0.0)
        )

        return ticket

    def get_bot_positions(self, symbol: Optional[str] = None) -> List[Any]:
        """Retrieves active positions opened by this bot."""
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        bot_positions = [pos for pos in positions if pos.magic == config.MAGIC_NUMBER]
        return bot_positions

    def update_sl(self, position, new_sl: float) -> bool:
        """Modifies Stop Loss in MT5."""
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": position.ticket,
            "symbol": position.symbol,
            "sl": round(new_sl, 5),
            "tp": position.tp,
            "magic": config.MAGIC_NUMBER
        }
        result = mt5.order_send(request)
        return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

    def close_partial_position(self, position, close_volume: float) -> bool:
        """Closes a partial volume of an active position (e.g. 50% scale-out)."""
        tick = self.connector.get_symbol_tick(position.symbol)
        if not tick:
            return False

        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask
        filling = self.get_filling_mode(position.symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": float(close_volume),
            "type": order_type,
            "price": price,
            "deviation": config.DEVIATION_POINTS,
            "magic": config.MAGIC_NUMBER,
            "comment": "Exness_PartialTP",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)
        return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

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
                be_trigger = risk_dist * 0.75
                be_offset = risk_dist * 0.10
                trail_dist = risk_dist
                trail_step = risk_dist * 0.20
                partial_tp_dist = risk_dist * 1.0
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
                            if is_crypto:
                                pnl_banked = round(current_profit_distance * close_vol, 2)
                            else:
                                pips_banked = current_profit_distance / pip_size
                                pnl_banked = round(pips_banked * (close_vol / 0.01) * 0.10, 2)

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
                            if is_crypto:
                                pnl_banked = round(current_profit_distance * close_vol, 2)
                            else:
                                pips_banked = current_profit_distance / pip_size
                                pnl_banked = round(pips_banked * (close_vol / 0.01) * 0.10, 2)

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
        pos_meta = self.tracked_positions.pop(ticket, None)
        if not pos_meta:
            return

        deals = mt5.history_deals_get(position=ticket)
        pnl = 0.0
        exit_price = 0.0
        reason = "Stop Loss / Take Profit Hit"
        if deals:
            pnl = sum(d.profit + d.swap + d.commission for d in deals)
            exit_price = deals[-1].price

        acc = self.connector.get_account_summary()
        balance = acc.get("balance", 0.0) if acc else 0.0
        sym = pos_meta.get("symbol", config.SYMBOL)
        pip_size = self.connector.get_pip_size(sym)
        pips = round((exit_price - pos_meta["entry"]) / pip_size, 1) if pos_meta.get("signal") == "BUY" else round((pos_meta["entry"] - exit_price) / pip_size, 1)

        self.journal.record_exit(ticket, exit_price, pips, pnl, balance, reason)

        is_win = pnl >= 0
        if self.risk_manager:
            self.risk_manager.register_trade_outcome(is_win)

        self.notifier.notify_trade_closed(ticket, sym, pnl, balance, reason)

    def check_friday_auto_close(self, symbols: List[str]) -> bool:
        """Closes all active positions on Friday before weekend gap risk."""
        if not config.FRIDAY_AUTO_CLOSE_ENABLED:
            return False

        now_utc = datetime.now(timezone.utc)
        if now_utc.weekday() == 4 and now_utc.hour >= config.FRIDAY_CUTOFF_HOUR_UTC:
            positions = self.get_bot_positions()
            if positions:
                logger.info(f"Friday cutoff reached ({now_utc.hour:02d}:00 UTC). Auto-closing {len(positions)} positions.")
                for pos in positions:
                    self.close_position(pos, reason="Friday Weekend Gap Protection")
                return True
        return False

    def close_position(self, position, reason: str = "Manual / System Close") -> bool:
        """Closes an active position immediately at market price."""
        tick = self.connector.get_symbol_tick(position.symbol)
        if not tick:
            return False

        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask
        filling = self.get_filling_mode(position.symbol)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": position.ticket,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "price": price,
            "deviation": config.DEVIATION_POINTS,
            "magic": config.MAGIC_NUMBER,
            "comment": f"Close: {reason[:20]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Closed position #{position.ticket} ({reason})")
            acc = self.connector.get_account_summary()
            balance = acc.get("balance", 0.0) if acc else 0.0
            
            pip_size = self.connector.get_pip_size(position.symbol)
            pips = round((price - position.price_open) / pip_size, 1) if position.type == mt5.ORDER_TYPE_BUY else round((position.price_open - price) / pip_size, 1)
            self.journal.record_exit(position.ticket, price, pips, position.profit, balance, reason)
            
            if self.risk_manager:
                self.risk_manager.register_trade_outcome(position.profit >= 0)

            self.notifier.notify_trade_closed(position.ticket, position.symbol, position.profit, balance, reason)
            return True
        return False
