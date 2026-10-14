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
        current_sig: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Manages Closed Trade Detection, Partial TP, Break-Even, Dynamic TP Magnet,
        Time-Decay harvesting, and Early Structural Defense for Gold scalping positions.
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
            self.last_exit_outcome = ct.get("outcome", "WIN")

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
                    "first_seen_time": time.time(),
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
        trail_dist = getattr(config_gold, "TRAILING_PROFIT_DISTANCE_USD", round(atr_val * getattr(config_gold, "TRAILING_ATR_MULT", 1.25), digits))
        trail_step = getattr(config_gold, "TRAILING_STEP_USD", 0.20)

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
                current_sig=current_sig,
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
        current_sig: Optional[str] = None,
    ):
        """
        Smart Adaptive Position Management:
        0. Early Structural Defense: Cuts losing position early if confirmed opposite signal occurs.
        1. Dynamic TP Magnet (Adaptive Profit Compression / Stall Exit with Time-Decay):
           - Minutes 0 to 6: Targets +$0.75 to +$1.20+. Exits if profit stalls 20s or pulls back 20¢ from peak.
           - After 6 minutes (Sluggish Trade): Lowers bar to +$0.40. Exits if profit stalls 15s or pulls back 15¢.
        2. Safe Ratchet Trailing Stop (NO Premature Breakeven!):
           Only activates when floating profit exceeds +$1.30, maintaining a wide $0.70 breathing
           cushion so the trade is never choked prematurely at +$0.50.
        """
        entry = p.price_open
        ticket = p.ticket
        cur_sl = p.sl
        cur_vol = p.volume
        is_buy = (direction == 1)

        current_price = tick.bid if is_buy else tick.ask
        profit_dist = (current_price - entry) if is_buy else (entry - current_price)

        # Retrieve or initialize position state tracking
        if ticket not in self.tracked_positions:
            self.tracked_positions[ticket] = {
                "ticket": ticket,
                "symbol": self.symbol,
                "signal": "BUY" if is_buy else "SELL",
                "lot": cur_vol,
                "entry": entry,
                "sl": cur_sl,
                "tp": p.tp,
                "peak_profit": profit_dist,
                "peak_time": time.time(),
                "profit_start_time": time.time() if profit_dist > 0 else None,
                "entry_time": getattr(p, "time", time.time()),
                "first_seen_time": time.time(),
            }

        pos_data = self.tracked_positions[ticket]
        if "first_seen_time" not in pos_data:
            pos_data["first_seen_time"] = time.time()

        elapsed_sec = time.time() - pos_data["first_seen_time"]
        elapsed_min = elapsed_sec / 60.0

        # Update peak floating profit observed
        if profit_dist > pos_data.get("peak_profit", 0.0):
            pos_data["peak_profit"] = profit_dist
            pos_data["peak_time"] = time.time()

        peak_profit = pos_data.get("peak_profit", 0.0)

        # -------------------------------------------------------------
        # 0. EARLY STRUCTURAL INVALIDATION DEFENSE
        # -------------------------------------------------------------
        if getattr(config_gold, "ENABLE_EARLY_STRUCTURE_DEFENSE", True) and current_sig in ["BUY", "SELL"]:
            is_opposite = (is_buy and current_sig == "SELL") or (not is_buy and current_sig == "BUY")
            if is_opposite and profit_dist < 0:
                exit_reason = f"Structural Defense: Flipped to {current_sig} (Early exit at ${profit_dist:+.2f})"
                logger.info(f"🛡️ {exit_reason} on Gold #{ticket}")
                self.close_position(p, reason=exit_reason)
                return

        # Stage 0: Scaled Multi-lot Partial TP (for accounts trading >= 0.02 lot)
        if cur_vol >= (min_vol * 2) and profit_dist >= target_tp1 and ticket not in self.active_be_locked:
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
                self.active_be_locked.add(ticket)
                logger.info(f"🎯 TP1 hit on Gold #{ticket}: Closed {close_vol} lots @ {current_price:.2f}")

        # -------------------------------------------------------------
        # 1. DYNAMIC TP MAGNET (With Time-Decay for Sluggish Trades)
        # -------------------------------------------------------------
        time_decay_mins = getattr(config_gold, "TIME_DECAY_MINUTES", 6.0)
        is_sluggish = (elapsed_min >= time_decay_mins)

        if is_sluggish:
            # Sluggish Trade (> 6 mins): Lower threshold to bank +$0.40 - $0.60
            min_compress = getattr(config_gold, "DECAYED_PROFIT_TRIGGER_USD", 0.40)
            stall_sec = getattr(config_gold, "DECAYED_STALL_SECONDS", 15)
            pullback_tol = getattr(config_gold, "DECAYED_PULLBACK_TOLERANCE_USD", 0.15)
            min_harvest_floor = 0.30
            stall_target = 0.40
            tag_name = f"Sluggish ({elapsed_min:.1f}m)"
        else:
            # Fresh Scalp (<= 6 mins): Target standard momentum +$0.75 - $1.20+
            min_compress = getattr(config_gold, "MIN_PROFIT_COMPRESS_USD", 0.75)
            stall_sec = getattr(config_gold, "STALL_DETECTION_SECONDS", 20)
            pullback_tol = getattr(config_gold, "PEAK_PULLBACK_TOLERANCE_USD", 0.20)
            min_harvest_floor = 0.60
            stall_target = 0.90
            tag_name = "Momentum"

        if profit_dist >= min_compress:
            if pos_data.get("profit_start_time") is None:
                pos_data["profit_start_time"] = time.time()

            peak_age = time.time() - pos_data.get("peak_time", time.time())

            # Condition A: Pullback from peak while still in harvest zone
            is_pullback_exit = (peak_profit >= (min_compress + 0.10) and profit_dist <= (peak_profit - pullback_tol) and profit_dist >= min_harvest_floor)
            # Condition B: Floating in solid profit and stalled for stall_sec without printing higher high
            is_stall_exit = (profit_dist >= stall_target and peak_age >= stall_sec)

            if is_pullback_exit or is_stall_exit:
                detail = f"Pullback from ${peak_profit:.2f}" if is_pullback_exit else f"Stalled for {int(peak_age)}s"
                exit_reason = f"TP Magnet Exit [{tag_name}] (+${profit_dist:.2f} | {detail})"
                logger.info(f"🧲 {exit_reason} on Gold #{ticket}")
                self.close_position(p, reason=exit_reason)
                return

        # -------------------------------------------------------------
        # 2. SAFE RATCHET TRAILING STOP (NO Premature Breakeven Choking!)
        # -------------------------------------------------------------
        # Never moves SL at +$0.50!
        # Only activates when profit is already past +$1.30, maintaining a wide $0.70 breathing cushion.
        trail_trigger = getattr(config_gold, "TRAILING_PROFIT_TRIGGER_USD", 1.30)
        trail_buffer = getattr(config_gold, "TRAILING_PROFIT_DISTANCE_USD", 0.70)
        ratchet_step = getattr(config_gold, "TRAILING_STEP_USD", 0.20)

        if getattr(config_gold, "ENABLE_TRAILING_STOP", True) and profit_dist >= trail_trigger:
            if is_buy:
                target_sl = round(current_price - trail_buffer, digits)
                stored_sl = self.trailing_sl.get(ticket, cur_sl)
                can_advance = (target_sl >= stored_sl + ratchet_step) and (target_sl > cur_sl)
            else:
                target_sl = round(current_price + trail_buffer, digits)
                stored_sl = self.trailing_sl.get(ticket, cur_sl if cur_sl > 0 else (target_sl + 1.0))
                can_advance = (cur_sl == 0 or target_sl <= stored_sl - ratchet_step) and (cur_sl == 0 or target_sl < cur_sl)

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
                    logger.info(f"📈 Smart Ratchet SL Advanced on Gold #{ticket}: SL -> ${target_sl:.2f} (Profit: +${profit_dist:.2f}, Cushion: ${trail_buffer:.2f})")
                    try:
                        if self.notifier and getattr(self.notifier, "enabled", False):
                            self.notifier.notify_trailing_stop_updated(self.symbol, ticket, target_sl)
                    except Exception as notify_err:
                        logger.warning(f"Discord notify error: {notify_err}")

    def execute_scalp(self, sig: str, atr_val: float, decision_basis: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """Executes a validated Gold scalp order with wide structural breathing room."""
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

        # Volatility Shield: Disallow scalping when ATR is wild (NY open / high impact spikes)
        max_allowed_atr = getattr(config_gold, "MAX_ALLOWED_ATR_USD", 4.00)
        if atr_val > max_allowed_atr:
            logger.warning(
                f"❌ Execution blocked: Current M5 Gold ATR (${atr_val:.2f}) exceeds maximum allowed (${max_allowed_atr:.2f}). Market in wild volatility expansion."
            )
            return None

        digits = info.digits
        entry = tick.ask if sig == "BUY" else tick.bid

        # Wide Structural Stop Loss: Gives Gold $3.80 - $4.50 of breathing room against normal noise
        max_sl_cap = getattr(config_gold, "MAX_SL_DOLLARS", 4.50)
        atr_mult = getattr(config_gold, "ATR_SL_MULTIPLIER", 1.30)
        stop_dist = round(min(max_sl_cap, max(3.50, atr_val * atr_mult)), digits)

        # Dynamic Initial Take Profit ($1.80) to be actively managed by the TP Magnet
        init_tp = getattr(config_gold, "INITIAL_TP_DOLLARS", 1.80)
        tp_dist = round(init_tp, digits)

        sl = round(entry - stop_dist if sig == "BUY" else entry + stop_dist, digits)
        tp = round(entry + tp_dist if sig == "BUY" else entry - tp_dist, digits)

        acc = mt5.account_info()
        equity = acc.equity if acc else 80.0

        # Compounding Scaling:
        # Micro protection: Enforce 0.01 lot under $150 equity (caps risk at max $2.50).
        # Above $150 equity: scales dynamically by 0.01 lot per $100 equity (e.g. $150 -> 0.02, $250 -> 0.03, etc.)
        gold_scale_thresh = getattr(config_gold, "TWO_TIER_EQUITY_THRESHOLD", 150.0)
        if getattr(config_gold, "ENABLE_TWO_TIER_SCALING", True) and equity >= gold_scale_thresh:
            scaled_units = int(equity // 100.0)
            target_lots = round(max(0.02, min(0.10, scaled_units * 0.01)), 2)
        else:
            target_lots = getattr(config_gold, "BASE_LOT_SIZE", 0.01)

        lots = max(info.volume_min, min(info.volume_max, target_lots))

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
                decision_basis=decision_basis,
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
