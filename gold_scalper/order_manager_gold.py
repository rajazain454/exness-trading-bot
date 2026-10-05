import logging
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import MetaTrader5 as mt5

try:
    from gold_scalper import config_gold
except ImportError:
    import config_gold

from crypto_forex_bot.base_order_manager import BaseOrderManager

from crypto_forex_bot.notifier import DiscordNotifier
from crypto_forex_bot.journal import TradeJournal

logger = logging.getLogger("GoldOrderManager")


class GoldOrderManager(BaseOrderManager):
    """
    Specialized Order & Position Manager for Institutional Gold (XAUUSDm) Scalper.
    Inherits unified broker execution, deal tracking, position hydration,
    and journal logging from BaseOrderManager.
    """

    def __init__(
        self,
        connector: Any,
        notifier: Optional[Any] = None,
        journal: Optional[Any] = None,
        risk_manager: Optional[Any] = None,
    ):
        super().__init__(
            connector=connector,
            magic_number=config_gold.MAGIC_NUMBER,
            notifier=notifier or DiscordNotifier(config_gold.DISCORD_WEBHOOK_URL),
            journal=journal or TradeJournal(),
            risk_manager=risk_manager,
            deviation_points=20,
        )
        self.symbol = config_gold.SYMBOL
        self.last_exit_m5_bar_time = 0
        self.active_be_locked = set()
        self.trailing_sl: Dict[int, float] = {}
        self.last_trail_price: Dict[int, float] = {}
        # Hydrate active positions on startup
        self.hydrate_active_positions(self.symbol)

    def get_gold_positions(self) -> List[Any]:
        """Retrieves active Gold positions placed by this scalper."""
        return self.get_bot_positions(self.symbol)

    def manage_gold_positions(
        self,
        atr_val: float,
        current_m5_bar_time: int = 0,
        positions: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Manages Closed Trade Detection, Partial TP, Break-Even, and Dynamic ATR Trailing Stop
        for Gold scalping positions.
        """
        active_positions = positions if positions is not None else self.get_gold_positions()
        active_tickets = {p.ticket for p in active_positions}

        # 1. Closed Trade Detection & SQLite Journal logging via BaseOrderManager
        closed_trades = self.detect_and_handle_closed_positions(
            current_positions=active_positions,
            symbol=self.symbol,
        )
        for ct in closed_trades:
            t = ct["ticket"]
            self.active_be_locked.discard(t)
            self.trailing_sl.pop(t, None)
            self.last_trail_price.pop(t, None)
            if current_m5_bar_time > 0:
                self.last_exit_m5_bar_time = current_m5_bar_time

        # 2. Track all active positions in tracked_positions with crash-resilient BE recovery
        for p in active_positions:
            is_buy = (p.type == mt5.ORDER_TYPE_BUY)
            # Automatic crash recovery: detect if position SL is already at or past break-even
            is_be_already = (is_buy and p.sl >= p.price_open) or (not is_buy and p.sl <= p.price_open and p.sl > 0)
            if p.ticket not in self.tracked_positions:
                sig_type = "BUY" if is_buy else "SELL"
                self.tracked_positions[p.ticket] = {
                    "ticket": p.ticket,
                    "symbol": self.symbol,
                    "signal": sig_type,
                    "lot": p.volume,
                    "entry": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "be_locked": is_be_already,
                    "partial_closed": is_be_already,
                    "trailing_sl": p.sl,
                    "last_trail_price": p.price_open,
                    "entry_time": getattr(p, "time", time.time()),
                }
            elif is_be_already:
                self.tracked_positions[p.ticket]["be_locked"] = True

            if self.tracked_positions[p.ticket].get("be_locked"):
                self.active_be_locked.add(p.ticket)

        if not active_positions or atr_val <= 0:
            return closed_trades

        tick = mt5.symbol_info_tick(self.symbol)
        if not tick:
            return closed_trades

        # Management Spread Guard: Avoid partial closes or SL edits during extreme spread widenings
        spread_pts = (tick.ask - tick.bid) / 0.001
        max_mgmt_spread = getattr(config_gold, "MAX_SPREAD_POINTS", 200) * 1.5
        if spread_pts > max_mgmt_spread:
            logger.warning(f"Spread wide during management ({spread_pts:.0f} pts > {max_mgmt_spread:.0f} pts). Pausing SL updates.")
            return closed_trades

        info = mt5.symbol_info(self.symbol)
        digits = info.digits if info else 3
        min_vol = info.volume_min if info else 0.01

        tp1_mult = getattr(config_gold, "PARTIAL_TP_ATR_MULT", getattr(config_gold, "PARTIAL_TP_RATIO", 1.0))
        target_tp1 = atr_val * tp1_mult
        be_buffer = getattr(config_gold, "BREAK_EVEN_BUFFER_USD", getattr(config_gold, "BREAK_EVEN_BUFFER_PIPS", 2.0) * 0.10)
        trail_dist = round(atr_val * config_gold.TRAILING_ATR_MULT, digits)
        trail_step = getattr(config_gold, "TRAILING_STEP_USD", 0.25)

        for p in active_positions:
            direction = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
            self._manage_single_position(
                p=p,
                tick=tick,
                direction=direction,
                digits=digits,
                min_vol=min_vol,
                target_tp1=target_tp1,
                be_buffer=be_buffer,
                trail_dist=trail_dist,
                trail_step=trail_step,
            )

        return closed_trades

    def _manage_single_position(
        self,
        p: Any,
        tick: Any,
        direction: int,
        digits: int,
        min_vol: float,
        target_tp1: float,
        be_buffer: float,
        trail_dist: float,
        trail_step: float,
    ):
        """Unified position management routine for both BUY and SELL Gold scalps."""
        entry = p.price_open
        ticket = p.ticket
        cur_sl = p.sl
        cur_vol = p.volume
        is_buy = (direction == 1)

        current_price = tick.bid if is_buy else tick.ask
        profit_dist = (current_price - entry) if is_buy else (entry - current_price)

        # Stage 1: Partial TP and Break-Even lock
        if profit_dist >= target_tp1 and ticket not in self.active_be_locked:
            if cur_vol >= (min_vol * 2):
                close_vol = round(cur_vol / 2.0, 2)
                close_order_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": ticket,
                    "symbol": self.symbol,
                    "volume": close_vol,
                    "type": close_order_type,
                    "price": current_price,
                    "deviation": self.deviation_points,
                    "magic": self.magic_number,
                    "comment": "Gold Scalp TP1 Partial",
                    "type_filling": self.get_filling_mode(self.symbol),
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"🎯 TP1 hit on Gold #{ticket}: Closed {close_vol} lots @ {current_price:.2f}")

            new_sl = round(entry + (be_buffer * direction), digits)
            is_better_sl = (new_sl > cur_sl) if is_buy else (cur_sl == 0 or new_sl < cur_sl)
            if is_better_sl:
                mod_req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "symbol": self.symbol,
                    "sl": new_sl,
                    "tp": p.tp,
                    "magic": self.magic_number,
                }
                res = mt5.order_send(mod_req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    self.active_be_locked.add(ticket)
                    if ticket in self.tracked_positions:
                        self.tracked_positions[ticket]["be_locked"] = True
                    self.trailing_sl[ticket] = new_sl
                    self.last_trail_price[ticket] = current_price
                    logger.info(f"🛡️ Risk-Free Lock: SL moved to Break-Even ({new_sl:.2f}) on Gold #{ticket}")

        # Stage 2: Dynamic ATR Trailing Stop (Active once Break-Even is locked)
        elif config_gold.ENABLE_TRAILING_STOP and ticket in self.active_be_locked:
            if is_buy:
                target_sl = round(current_price - trail_dist, digits)
                last_sl = max(cur_sl, self.trailing_sl.get(ticket, cur_sl))
                last_price = self.last_trail_price.get(ticket, entry)
                can_advance = (current_price > last_price + trail_step) and (target_sl >= last_sl + trail_step)
            else:
                target_sl = round(current_price + trail_dist, digits)
                last_sl = min(cur_sl, self.trailing_sl.get(ticket, cur_sl)) if cur_sl > 0 else self.trailing_sl.get(ticket, target_sl + 1.0)
                last_price = self.last_trail_price.get(ticket, entry)
                can_advance = (current_price < last_price - trail_step) and (target_sl <= last_sl - trail_step)

            if can_advance:
                mod_req = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": ticket,
                    "symbol": self.symbol,
                    "sl": target_sl,
                    "tp": p.tp,
                    "magic": self.magic_number,
                }
                res = mt5.order_send(mod_req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    self.trailing_sl[ticket] = target_sl
                    self.last_trail_price[ticket] = current_price
                    logger.info(f"📈 Trailing Stop Advanced on Gold #{ticket}: SL -> ${target_sl:.2f} (Locking profit)")
                    try:
                        if self.notifier and getattr(self.notifier, "enabled", False):
                            self.notifier.notify_trailing_stop_updated(self.symbol, ticket, target_sl)
                    except Exception as notify_err:
                        logger.warning(f"Discord notify error: {notify_err}")

    def execute_scalp(self, sig: str, atr_val: float) -> Optional[int]:
        """Executes a validated Gold scalp order with dynamic 1:2 R:R matching the EA."""
        # Double-check position count immediately
        current_positions = self.get_gold_positions()
        if len(current_positions) >= config_gold.MAX_OPEN_POSITIONS:
            return None

        tick = mt5.symbol_info_tick(self.symbol)
        info = mt5.symbol_info(self.symbol)
        if not tick or not info:
            return None

        # Pre-execution Spread Check
        spread_pts = (tick.ask - tick.bid) / 0.001
        max_allowed_spread = getattr(config_gold, "MAX_SPREAD_POINTS", 200)
        if spread_pts > max_allowed_spread:
            logger.warning(
                f"❌ Execution blocked: Current spread ({spread_pts:.0f} pts) exceeds maximum allowed ({max_allowed_spread} pts)."
            )
            return None

        digits = info.digits
        entry = tick.ask if sig == "BUY" else tick.bid
        stop_dist = atr_val * config_gold.ATR_SL_MULTIPLIER

        # Dynamic 1:2 R:R Take Profit (Aligned with EA InpAtrMultiplierTP)
        tp_dist = round(stop_dist * config_gold.ATR_TP_MULTIPLIER, digits)

        sl = round(entry - stop_dist if sig == "BUY" else entry + stop_dist, digits)
        tp = round(entry + tp_dist if sig == "BUY" else entry - tp_dist, digits)

        acc = mt5.account_info()
        equity = acc.equity if acc else 30.0
        risk_usd = equity * (config_gold.RISK_PER_TRADE_PERCENT / 100.0)
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
            "deviation": self.deviation_points,
            "magic": self.magic_number,
            "comment": "Gold Institutional Scalp",
            "type_filling": self.get_filling_mode(self.symbol),
        }

        # Pre-flight Margin Verification
        req_margin = mt5.order_calc_margin(req["type"], self.symbol, lots, entry)
        free_margin = acc.margin_free if acc else 0.0
        if req_margin and req_margin > free_margin:
            shortfall = req_margin - free_margin
            logger.warning(
                f"❌ Margin Shortfall: {lots} lot Gold requires ${req_margin:.2f} margin "
                f"(Free: ${free_margin:.2f}, Leverage 1:{acc.leverage if acc else 50}). "
                f"Shortfall: ${shortfall:.2f}. Increase Exness account leverage to 1:200+ in Personal Area."
            )
            return None

        t0 = time.perf_counter()
        res = mt5.order_send(req)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            executed_price = res.price if getattr(res, "price", 0.0) else entry
            pip_size = self.connector.get_pip_size(self.symbol)
            slippage_pips = round(abs(executed_price - entry) / max(pip_size, 1e-5), 1)

            self.record_new_position(
                ticket=res.order,
                symbol=self.symbol,
                signal=sig,
                lot=lots,
                entry_price=executed_price,
                sl=sl,
                tp=tp,
                latency_ms=latency_ms,
                slippage_pips=slippage_pips,
            )
            logger.info(
                f"⚡ EXECUTED {sig} on Gold #{res.order} | Lots: {lots:.2f} @ {executed_price:.2f} | "
                f"Latency: {latency_ms:.1f}ms | Slippage: {slippage_pips:.1f}p"
            )
            return res.order
        else:
            err = res.comment if res else str(mt5.last_error())
            logger.error(f"Execution failed on Gold: {err}")
            return None
