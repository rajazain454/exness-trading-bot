import logging
import time
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import MetaTrader5 as mt5

logger = logging.getLogger("BaseOrderManager")


class BaseOrderManager:
    """
    Unified Base Order Manager & Position Tracker.
    Shared execution engine across both the Multi-Asset Swing Bot and the Institutional Gold Scalper.

    Provides:
    - Broker filling mode detection (IOC vs FOK)
    - Active and pending position discovery filtered by magic number
    - Position state hydration across bot restarts (BE lock, partial close recovery)
    - Standardized order modifications (SL/TP, partial volume scale-outs, market closures)
    - Deal history auditing and robust SQLite trade journal exit logging
    - Real-time Discord trade notifications
    """

    notifier: Any = None
    journal: Any = None
    risk_manager: Any = None

    def __init__(
        self,
        connector: Any,
        magic_number: int,
        notifier: Optional[Any] = None,
        journal: Optional[Any] = None,
        risk_manager: Optional[Any] = None,
        deviation_points: int = 20,
    ):
        self.connector = connector
        self.magic_number = magic_number
        self.notifier = notifier
        self.journal = journal
        self.risk_manager = risk_manager
        self.deviation_points = deviation_points
        self.tracked_positions: Dict[int, Dict[str, Any]] = {}

    def get_filling_mode(self, symbol: str) -> int:
        """Determines the appropriate order filling mode supported by the broker for the symbol."""
        info = mt5.symbol_info(symbol)
        if not info:
            return mt5.ORDER_FILLING_IOC

        filling_mode = info.filling_mode
        if filling_mode & 2:
            return mt5.ORDER_FILLING_IOC
        elif filling_mode & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_IOC

    def get_bot_positions(self, symbol: Optional[str] = None) -> List[Any]:
        """Retrieves active positions opened by this bot matching its magic number."""
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        return [pos for pos in positions if pos.magic == self.magic_number]

    def get_pending_orders(self, symbol: Optional[str] = None) -> List[Any]:
        """Retrieves active pending orders opened by this bot matching its magic number."""
        orders = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        if orders is None:
            return []
        return [o for o in orders if o.magic == self.magic_number]

    def get_bot_active_and_pending_count(self, symbol: Optional[str] = None) -> int:
        """Counts both filled positions and unfilled pending orders."""
        positions = self.get_bot_positions(symbol)
        pending = self.get_pending_orders(symbol)
        return len(positions) + len(pending)

    def hydrate_active_positions(self, symbol: Optional[str] = None):
        """
        Restores tracking state for all open MT5 positions for this bot's magic number.
        Ensures trailing stops, break-even locks, partial TP, and journal exit logging
        work seamlessly across bot restarts.
        """
        positions = self.get_bot_positions(symbol)
        if not positions:
            return

        for pos in positions:
            ticket = pos.ticket
            if ticket in self.tracked_positions:
                continue

            trade = self.journal.get_trade(ticket) if self.journal else None
            signal = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
            entry_price = float(pos.price_open)
            sl = float(pos.sl)
            tp = float(pos.tp)
            volume = float(pos.volume)

            be_locked = False
            partial_closed = False

            if trade:
                signal = trade.get("signal", signal)
                orig_lot = trade.get("lot", volume)
                entry_price = trade.get("entry_price", entry_price)
                if volume < orig_lot:
                    partial_closed = True

            pip_size = self.connector.get_pip_size(pos.symbol)
            if (signal == "BUY" and sl >= entry_price) or (signal == "SELL" and sl > 0 and sl <= entry_price):
                be_locked = True

            self.tracked_positions[ticket] = {
                "ticket": ticket,
                "symbol": pos.symbol,
                "signal": signal,
                "entry": entry_price,
                "lot": volume,
                "sl": sl,
                "tp": tp,
                "be_locked": be_locked,
                "partial_closed": partial_closed,
                "trailing_sl": sl if be_locked else 0.0,
                "last_trail_price": entry_price if be_locked else 0.0,
                "entry_time": getattr(pos, "time", time.time()),
            }

            if not trade and self.journal:
                self.journal.record_entry(
                    ticket=ticket,
                    symbol=pos.symbol,
                    signal=signal,
                    lot=volume,
                    entry_price=entry_price,
                    sl=sl,
                    tp=tp,
                    latency_ms=0.0,
                    slippage_pips=0.0,
                )

            logger.info(
                f"Hydrated active position #{ticket} ({pos.symbol}, {signal}, {volume} lot). "
                f"BE: {be_locked}, Partial Closed: {partial_closed}"
            )

    def record_new_position(
        self,
        ticket: int,
        symbol: str,
        signal: str,
        lot: float,
        entry_price: float,
        sl: float,
        tp: float,
        latency_ms: float = 0.0,
        slippage_pips: float = 0.0,
    ):
        """Registers a freshly opened position into tracked state, SQLite journal, and Discord alerts."""
        self.tracked_positions[ticket] = {
            "ticket": ticket,
            "symbol": symbol,
            "signal": signal,
            "lot": float(lot),
            "entry": float(entry_price),
            "sl": float(sl),
            "tp": float(tp),
            "be_locked": False,
            "partial_closed": False,
            "trailing_sl": float(sl),
            "last_trail_price": float(entry_price),
            "entry_time": time.time(),
        }

        try:
            if self.journal:
                self.journal.record_entry(
                    ticket=ticket,
                    symbol=symbol,
                    signal=signal,
                    lot=float(lot),
                    entry_price=float(entry_price),
                    sl=float(sl),
                    tp=float(tp),
                    latency_ms=round(latency_ms, 1),
                    slippage_pips=round(slippage_pips, 1),
                )
        except Exception as j_err:
            logger.warning(f"Journal entry recording error for #{ticket}: {j_err}")

        try:
            if self.notifier and getattr(self.notifier, "enabled", False):
                acc = self.connector.get_account_summary() if hasattr(self.connector, "get_account_summary") else None
                balance = acc.get("balance", 0.0) if acc else (mt5.account_info().balance if mt5.account_info() else 0.0)
                self.notifier.notify_trade_opened(
                    symbol=symbol,
                    signal=signal,
                    ticket=ticket,
                    entry=entry_price,
                    sl=sl,
                    tp=tp,
                    lot=lot,
                    balance=balance,
                )
        except Exception as notify_err:
            logger.warning(f"Discord open notify error for #{ticket}: {notify_err}")

    def update_sl(
        self,
        position_or_ticket: Any,
        new_sl: float,
        symbol: Optional[str] = None,
        tp: Optional[float] = None,
    ) -> bool:
        """Modifies Stop Loss in MT5 safely."""
        if hasattr(position_or_ticket, "ticket"):
            ticket = position_or_ticket.ticket
            sym = position_or_ticket.symbol
            cur_tp = position_or_ticket.tp
        else:
            ticket = int(position_or_ticket)
            meta = self.tracked_positions.get(ticket, {})
            sym = symbol or meta.get("symbol", "")
            cur_tp = tp if tp is not None else meta.get("tp", 0.0)

        info = mt5.symbol_info(sym) if sym else None
        digits = info.digits if info else 5
        rounded_sl = round(new_sl, digits)

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": sym,
            "sl": rounded_sl,
            "tp": cur_tp,
            "magic": self.magic_number,
        }
        result = mt5.order_send(request)
        success = bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        if success and ticket in self.tracked_positions:
            self.tracked_positions[ticket]["sl"] = rounded_sl
        return success

    def close_partial_position(
        self,
        position: Any,
        close_volume: float,
        comment: str = "PartialTP",
    ) -> bool:
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
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        RETRIABLE_RETCODES = {
            getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004),
            getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10018),
            getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
            getattr(mt5, "TRADE_RETCODE_TIMEOUT", 10022),
            getattr(mt5, "TRADE_RETCODE_CONNECTION", 10031),
            10021,
        }

        result = None
        for attempt in range(1, 4):
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            retcode = result.retcode if result else -1
            if retcode in RETRIABLE_RETCODES and attempt < 3:
                time.sleep(0.2 * attempt)
                fresh_tick = self.connector.get_symbol_tick(position.symbol)
                if fresh_tick:
                    price = fresh_tick.bid if position.type == mt5.ORDER_TYPE_BUY else fresh_tick.ask
                    request["price"] = price
            else:
                break

        success = bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)
        if success and position.ticket in self.tracked_positions:
            self.tracked_positions[position.ticket]["partial_closed"] = True
            self.tracked_positions[position.ticket]["lot"] = round(position.volume - close_volume, 2)
        return success

    def close_position(self, position: Any, reason: str = "Manual / System Close") -> bool:
        """Closes an active position immediately at market price with retries."""
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
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": f"Close: {reason[:20]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        RETRIABLE_RETCODES = {
            getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004),
            getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10018),
            getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
            getattr(mt5, "TRADE_RETCODE_TIMEOUT", 10022),
            getattr(mt5, "TRADE_RETCODE_CONNECTION", 10031),
            10021,
        }

        result = None
        for attempt in range(1, 4):
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                break
            retcode = result.retcode if result else -1
            if retcode in RETRIABLE_RETCODES and attempt < 3:
                time.sleep(0.2 * attempt)
                fresh_tick = self.connector.get_symbol_tick(position.symbol)
                if fresh_tick:
                    price = fresh_tick.bid if position.type == mt5.ORDER_TYPE_BUY else fresh_tick.ask
                    request["price"] = price
            else:
                break

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Closed position #{position.ticket} ({reason})")
            self.detect_and_handle_closed_positions()
            return True
        return False

    def detect_and_handle_closed_positions(
        self,
        current_positions: Optional[List[Any]] = None,
        symbol: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Audits active MT5 positions against tracked_positions.
        For any position that has closed (SL, TP, or manual), queries MT5 deal history,
        calculates net PnL (including swap & commission), records exit in SQLite journal,
        notifies Discord, and updates risk manager outcome.
        Returns a list of closed trade summary dicts.
        """
        if current_positions is None:
            current_positions = self.get_bot_positions(symbol)

        active_tickets = {p.ticket for p in current_positions}
        closed_tickets = [
            t for t, meta in list(self.tracked_positions.items())
            if (symbol is None or meta.get("symbol") == symbol) and t not in active_tickets
        ]

        closed_summaries = []
        for ticket in closed_tickets:
            meta = self.tracked_positions.pop(ticket, {})
            deals = mt5.history_deals_get(position=ticket)
            pnl = 0.0
            exit_price = meta.get("entry", 0.0)
            close_reason = "Manual / Target Close"

            if deals:
                pnl = sum(d.profit + d.swap + d.commission for d in deals)
                exit_deal = deals[-1]
                exit_price = exit_deal.price if getattr(exit_deal, "price", 0.0) > 0 else exit_price
                cmt = (exit_deal.comment or "").lower()
                if "sl" in cmt:
                    close_reason = "Trailing Stop / SL Hit"
                elif "tp" in cmt:
                    close_reason = "Take Profit Hit"
                else:
                    close_reason = "Manual / Discretionary Close"

            acc = self.connector.get_account_summary() if hasattr(self.connector, "get_account_summary") else None
            balance = acc.get("balance", 0.0) if acc else (mt5.account_info().balance if mt5.account_info() else 0.0)

            trade_sym = meta.get("symbol", symbol or "")
            pip_size = self.connector.get_pip_size(trade_sym) if trade_sym else 0.0001
            entry_p = meta.get("entry", exit_price)

            if meta.get("signal") == "BUY":
                pips = round((exit_price - entry_p) / max(pip_size, 1e-5), 1)
            else:
                pips = round((entry_p - exit_price) / max(pip_size, 1e-5), 1)

            try:
                if self.journal:
                    self.journal.record_exit(
                        ticket=ticket,
                        exit_price=exit_price,
                        pips=pips,
                        pnl_usd=pnl,
                        balance_after=balance,
                        close_reason=close_reason,
                    )
            except Exception as j_err:
                logger.warning(f"Journal exit recording failed for #{ticket}: {j_err}")

            if self.risk_manager and hasattr(self.risk_manager, "register_trade_outcome"):
                self.risk_manager.register_trade_outcome(pnl >= 0)
            if self.risk_manager and hasattr(self.risk_manager, "register_symbol_exit"):
                self.risk_manager.register_symbol_exit(trade_sym, cooldown_minutes=10)

            try:
                if self.notifier and getattr(self.notifier, "enabled", False):
                    self.notifier.notify_trade_closed(
                        ticket=ticket,
                        symbol=trade_sym,
                        pnl_usd=pnl,
                        balance=balance,
                        reason=close_reason,
                    )
            except Exception as notify_err:
                logger.warning(f"Discord close notify failed for #{ticket}: {notify_err}")

            summary = {
                "ticket": ticket,
                "symbol": trade_sym,
                "signal": meta.get("signal", ""),
                "lot": meta.get("lot", 0.0),
                "entry": entry_p,
                "exit_price": exit_price,
                "pnl": pnl,
                "pips": pips,
                "reason": close_reason,
                "closed_at": time.time(),
            }
            closed_summaries.append(summary)
            logger.info(
                f"Trade Closed #{ticket} on {trade_sym} | PnL: ${pnl:+.2f} ({pips:+.1f} pips) | Reason: {close_reason}"
            )

        return closed_summaries
