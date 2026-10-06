import os
import json
import math
import logging
from datetime import datetime, timezone, date, time, timedelta
from typing import Tuple, Dict, Any, Optional, List
import MetaTrader5 as mt5
import config
from news_filter import EconomicNewsFilter
from notifier import DiscordNotifier
from quant_engine import QuantitativeEngine
from journal import TradeJournal

logger = logging.getLogger("RiskManager")

class RiskManager:
    """
    Quantitative Risk & Statistical Edge Engine:
    - Fractional Kelly Criterion Position Sizing
    - Volatility Regime Adaptive Risk:Reward (ATR Percentiles)
    - Mathematical Expected Value (EV) Gatekeeper
    - Flash Crash & Spread Anomaly Shield
    - Session liquidity hours & daily rollover spread blackout
    - Friday pre-weekend market close protection
    - Economic news blackout (ForexFactory integration)
    - Anti-Revenge Consecutive Loss Cooldown
    """

    def __init__(self, connector, notifier: Optional[DiscordNotifier] = None):
        self.connector = connector
        self.notifier = notifier or DiscordNotifier()
        self.journal = TradeJournal()
        self.news_filter = EconomicNewsFilter(
            pre_buffer_mins=config.NEWS_PRE_BUFFER_MINS,
            post_buffer_mins=config.NEWS_POST_BUFFER_MINS
        )
        self.today = date.today()
        self.daily_start_balance = 0.0
        self.daily_peak_equity = 0.0
        self.consecutive_losses = 0
        self.cooldown_until: Optional[datetime] = None
        self.symbol_cooldowns: Dict[str, datetime] = {}
        self.spread_history: Dict[str, List[float]] = {}
        self._sync_daily_balance()

    def _sync_daily_balance(self):
        """Initializes or resets daily balance checkpoint."""
        acc = self.connector.get_account_summary()
        if acc:
            self.daily_start_balance = acc["balance"]
            self.daily_peak_equity = max(acc["balance"], acc.get("equity", acc["balance"]))
            self.today = date.today()
            self.consecutive_losses = 0
            self.cooldown_until = None

    def check_new_day(self):
        """Resets daily circuit breakers on calendar rollover."""
        if date.today() != self.today:
            self._sync_daily_balance()
            logger.info("New trading day detected. Daily balance baseline synced.")

    def check_spread_anomaly(self, symbol: str) -> Tuple[bool, str]:
        """Tracks rolling spread history and detects abrupt flash crash liquidity spikes."""
        if not config.SPREAD_ANOMALY_ENABLED:
            return True, "Spread anomaly shield disabled"

        curr_spread = self.connector.get_current_spread_pips(symbol)
        if symbol not in self.spread_history:
            self.spread_history[symbol] = []

        history = self.spread_history[symbol]
        history.append(curr_spread)
        if len(history) > config.ROLLING_SPREAD_WINDOW:
            history.pop(0)

        if len(history) >= 5:
            avg_spread = sum(history) / len(history)
            if curr_spread >= (avg_spread * config.SPREAD_SPIKE_MULTIPLIER) and curr_spread >= 1.5:
                ratio = curr_spread / (avg_spread + 1e-9)
                return False, f"Flash Crash / Spread Anomaly: Current spread ({curr_spread:.1f}p) is {ratio:.1f}x higher than average ({avg_spread:.1f}p). Trade execution locked."

        return True, "Spread normal"

    def register_trade_outcome(self, is_win: bool):
        """Tracks consecutive outcomes and triggers anti-revenge cooldown if needed."""
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            logger.warning(f"Consecutive loss recorded: {self.consecutive_losses}/{config.MAX_CONSECUTIVE_LOSSES}")
            if self.consecutive_losses >= config.MAX_CONSECUTIVE_LOSSES:
                self.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=config.COOLDOWN_HOURS)
                logger.warning(f"Anti-revenge cooldown triggered! No new trades until {self.cooldown_until.strftime('%H:%M:%S UTC')}")
                self.notifier.notify_cooldown_activated(self.consecutive_losses, config.COOLDOWN_HOURS)

    # Backward compatibility alias
    record_trade_result = register_trade_outcome

    def check_cooldown(self) -> Tuple[bool, str]:
        """Verifies if the bot is currently in a consecutive loss cooldown."""
        if self.cooldown_until is not None:
            now_utc = datetime.now(timezone.utc)
            if now_utc < self.cooldown_until:
                remaining_mins = int((self.cooldown_until - now_utc).total_seconds() / 60)
                return False, f"Consecutive loss cooldown active ({remaining_mins} mins remaining)."
            else:
                self.cooldown_until = None
                self.consecutive_losses = 0
                logger.info("Consecutive loss cooldown expired. Normal trading resumed.")
        return True, "Cooldown clear"

    def register_symbol_exit(self, symbol: str, cooldown_minutes: int = 10):
        """Sets a post-exit cooldown on the specific symbol (2 completed M5 candles = 10 mins)."""
        if symbol:
            mins = getattr(config, "SAME_SYMBOL_COOLDOWN_MINUTES", cooldown_minutes)
            self.symbol_cooldowns[symbol] = datetime.now(timezone.utc) + timedelta(minutes=mins)
            logger.info(f"Post-Exit Cooldown: {symbol} paused for {mins}m (2 candles) until {self.symbol_cooldowns[symbol].strftime('%H:%M:%S UTC')}")

    def check_symbol_cooldown(self, symbol: str) -> Tuple[bool, str]:
        """Verifies if the specific symbol is cooling down from a recent exit to prevent re-entry top/bottom chop."""
        if symbol and symbol in self.symbol_cooldowns:
            now_utc = datetime.now(timezone.utc)
            expiry = self.symbol_cooldowns[symbol]
            if now_utc < expiry:
                remaining_mins = max(1, int((expiry - now_utc).total_seconds() / 60))
                return False, f"Post-exit cooldown active for {symbol} ({remaining_mins}m remaining, 2-candle rule). Preventing top/bottom re-entry chop."
            else:
                del self.symbol_cooldowns[symbol]
        return True, "Symbol cooldown clear"

    def check_trading_session(self, symbol: str = "") -> Tuple[bool, str]:
        """Verifies active liquidity sessions, midday European lunch lull, and rollover blackout."""
        if not config.SESSION_FILTER_ENABLED:
            return True, "Session filter disabled"

        # Crypto trades 24/7 continuously
        if symbol and any(c in symbol for c in ["BTC", "ETH", "SOL", "XRP"]):
            return True, "Crypto market open 24/7"

        now_utc = datetime.now(timezone.utc)
        curr_hour = now_utc.hour
        curr_min = now_utc.minute

        # Midday European Bank Lunch Lull (11:30 - 13:00 UTC) - Forex only
        if getattr(config, "MIDDAY_LULL_FILTER_ENABLED", True):
            if (curr_hour == 11 and curr_min >= 30) or (curr_hour == 12):
                return False, f"Midday Lull ({curr_hour:02d}:{curr_min:02d} UTC): Low institutional liquidity / bank lunch (11:30-13:00 UTC). Forex paused."

        r_start_h, r_start_m = map(int, config.ROLLOVER_BLACKOUT_START.split(":"))
        r_end_h, r_end_m = map(int, config.ROLLOVER_BLACKOUT_END.split(":"))
        curr_time_val = time(curr_hour, curr_min)
        if time(r_start_h, r_start_m) <= curr_time_val <= time(r_end_h, r_end_m):
            return False, f"Daily rollover spread blackout active ({config.ROLLOVER_BLACKOUT_START}-{config.ROLLOVER_BLACKOUT_END} UTC)."

        in_session = any(
            s["start_hour"] <= curr_hour < s["end_hour"]
            for s in config.ACTIVE_SESSIONS
        )

        if not in_session:
            return False, f"Outside active trading session ({curr_hour:02d}:{curr_min:02d} UTC). London/NY: 07:00-20:00 UTC."

        return True, "Trading session active"

    def check_friday_cutoff(self, symbol: str = "") -> Tuple[bool, str]:
        """Prevents opening new positions on Friday evening for Forex."""
        if not config.FRIDAY_AUTO_CLOSE_ENABLED:
            return True, "Weekend protection disabled"

        # Crypto does not close on weekends
        if symbol and any(c in symbol for c in ["BTC", "ETH", "SOL", "XRP"]):
            return True, "Crypto operates through weekends"

        now_utc = datetime.now(timezone.utc)
        if now_utc.weekday() == 4 and now_utc.hour >= config.FRIDAY_CUTOFF_HOUR_UTC:
            return False, f"Friday weekend cutoff reached ({now_utc.hour:02d}:00 UTC). New trades blocked."

        return True, "Weekend protection check passed"

    def calculate_lot_size(self, equity: float, symbol: str = "", sl_pips: float = 0.0) -> float:
        """
        Calculates position size using Fractional Kelly Criterion (or smart compounding).
        Dynamically adapts to the specific instrument's real pip/point dollar value and SL distance.
        f* = (p * b - (1 - p)) / b
        """
        if config.USE_KELLY_SIZING:
            is_crypto = any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"]) if symbol else False
            asset_type = "CRYPTO" if is_crypto else "FOREX"
            stats = self.journal.get_all_time_stats(asset_type=asset_type)

            if stats.get("total", 0) < 5:
                # Conservative defaults based on 1-year quant testing
                win_rate = 45.0 if is_crypto else 60.0
                avg_win = 4.50 if is_crypto else 2.50
                avg_loss = 1.50
            else:
                win_rate = stats.get("win_rate", 60.0)
                avg_win = stats.get("avg_win_usd", 2.50)
                avg_loss = stats.get("avg_loss_usd", 1.50)

            # Quarter-Kelly risk percentage
            safe_risk_fraction = QuantitativeEngine.calculate_kelly_fraction(
                win_rate=win_rate,
                avg_win_usd=avg_win,
                avg_loss_usd=avg_loss,
                fraction=config.KELLY_FRACTION
            )
            # Dollar risk budget
            risk_budget_usd = equity * safe_risk_fraction

            # Dynamic risk per 0.01 lot based on instrument and sl_pips
            if symbol and sl_pips > 0:
                pip_val_001 = self.connector.get_pip_dollar_value(symbol, 0.01)
                dollar_risk_001 = max(0.10, sl_pips * pip_val_001)
                calculated_units = risk_budget_usd / dollar_risk_001
            else:
                calculated_units = risk_budget_usd / (avg_loss if avg_loss > 0 else 1.50)

            lot = round(max(config.BASE_LOT_SIZE, calculated_units * 0.01), 2)
        else:
            # Fallback compounding
            multiplier = int(equity // config.CAPITAL_PER_001_LOT)
            lot = round(max(config.BASE_LOT_SIZE, multiplier * config.BASE_LOT_SIZE), 2)

        # Broker symbol compliance: volume_min, volume_max, volume_step
        s_info = mt5.symbol_info(symbol) if symbol else None
        if s_info:
            vol_min = s_info.volume_min if s_info.volume_min > 0 else config.BASE_LOT_SIZE
            vol_max = s_info.volume_max if s_info.volume_max > 0 else config.MAX_LOT_SIZE
            vol_step = s_info.volume_step if s_info.volume_step > 0 else 0.01

            steps = max(0, round((lot - vol_min) / vol_step))
            lot = max(vol_min, min(vol_max, vol_min + steps * vol_step))
            step_decimals = max(0, -int(math.log10(vol_step))) if vol_step < 1 else 0
            lot = round(min(lot, config.MAX_LOT_SIZE), step_decimals)
        else:
            lot = min(lot, config.MAX_LOT_SIZE)

        return lot

    # Backward compatibility alias
    calculate_compounding_lot = calculate_lot_size

    def can_open_trade(self, symbol: str, active_positions_count: int) -> Tuple[bool, str]:
        """
        Comprehensive pre-trade gatekeeper.
        Enforces position limits, spread anomalies, cooldowns, sessions, news, Friday cutoff, and margin.
        """
        self.check_new_day()

        if active_positions_count >= config.MAX_OPEN_POSITIONS:
            return False, f"Maximum open position limit ({config.MAX_OPEN_POSITIONS}) reached."

        # Verify broker allows trading on this specific symbol
        s_info = mt5.symbol_info(symbol) if symbol else None
        if s_info and s_info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
            return False, f"Trading is disabled for {symbol} on this broker account."

        anomaly_ok, anomaly_reason = self.check_spread_anomaly(symbol)
        if not anomaly_ok:
            return False, anomaly_reason

        cd_ok, cd_reason = self.check_cooldown()
        if not cd_ok:
            return False, cd_reason

        sym_cd_ok, sym_cd_reason = self.check_symbol_cooldown(symbol)
        if not sym_cd_ok:
            return False, sym_cd_reason

        fri_ok, fri_reason = self.check_friday_cutoff(symbol)
        if not fri_ok:
            return False, fri_reason

        sess_ok, sess_reason = self.check_trading_session(symbol)
        if not sess_ok:
            return False, sess_reason

        news_blackout, news_reason, _ = self.news_filter.is_news_blackout(symbol)
        if news_blackout:
            return False, news_reason

        acc = self.connector.get_account_summary()
        if not acc:
            return False, "Failed to retrieve account summary."

        if not acc["trade_allowed"]:
            return False, "Algo Trading is disabled in MT5 options or on broker."

        # Update intraday high-watermark
        if acc["equity"] > self.daily_peak_equity:
            self.daily_peak_equity = acc["equity"]

        daily_pnl = acc["equity"] - self.daily_start_balance
        if daily_pnl <= -config.MAX_DAILY_LOSS_USD:
            return False, f"Daily circuit breaker hit (-${abs(daily_pnl):.2f} / -${config.MAX_DAILY_LOSS_USD:.2f})."

        # Intraday High-Watermark (Peak Equity) Trailing Profit-Lock Circuit Breaker
        # If intraday realized/unrealized profit reached at least $3.00 (e.g. 10% on $30 capital)
        # and equity gives back 50% or more of that peak profit, halt new trades to secure daily gains.
        intraday_profit = self.daily_peak_equity - self.daily_start_balance
        if intraday_profit >= 3.0:
            giveback = self.daily_peak_equity - acc["equity"]
            if giveback >= (intraday_profit * 0.50):
                return False, (
                    f"Intraday trailing profit-lock circuit breaker: Equity pulled back ${giveback:.2f} "
                    f"from daily peak ${self.daily_peak_equity:.2f} (now ${acc['equity']:.2f}). "
                    f"Protecting accumulated daily gains."
                )

        spread_pips = self.connector.get_current_spread_pips(symbol)
        max_allowed_spread = getattr(config, "MAX_SPREAD_PIPS_CRYPTO", 2500.0) if any(c in symbol for c in ["BTC", "ETH", "SOL", "XRP"]) else getattr(config, "MAX_SPREAD_PIPS", 3.5)
        if spread_pips > max_allowed_spread:
            return False, f"Spread ({spread_pips:.1f} pips) exceeds maximum allowed ({max_allowed_spread:.1f} pips)."

        tick = self.connector.get_symbol_tick(symbol)
        if not tick:
            return False, "Failed to retrieve live market tick."

        lot_size = self.calculate_lot_size(acc["equity"], symbol=symbol)
        required_margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, lot_size, tick.ask)
        if required_margin is None:
            s_info = mt5.symbol_info(symbol)
            contract_size = s_info.trade_contract_size if s_info and s_info.trade_contract_size > 0 else 100000.0
            required_margin = (contract_size * lot_size * tick.ask) / acc.get("leverage", 50)

        if acc["free_margin"] < (required_margin + 2.0):
            return False, f"Insufficient Free Margin (${acc['free_margin']:.2f}). Need ~${required_margin:.2f}."

        return True, "Risk check passed."

    def calculate_sl_tp(self, symbol: str, signal: str, atr_value: float = 0.0, atr_percentile: float = 50.0) -> Optional[Dict[str, float]]:
        """
        Calculates volatility-adaptive SL & TP based on ATR Percentile Rank
        and verifies Mathematical Expected Value (EV).
        """
        tick = self.connector.get_symbol_tick(symbol)
        info = mt5.symbol_info(symbol)
        acc = self.connector.get_account_summary()
        if not tick or not info or not acc:
            return None

        pip_size = self.connector.get_pip_size(symbol)
        digits = info.digits

        # Volatility Regime Adaptive Multipliers (incorporating coin-specific trained TP target)
        from strategy import get_trained_params
        trained_p = get_trained_params(symbol)
        default_tp_mult = trained_p.get("base_tp_mult", config.ATR_TP_MULTIPLIER)

        if config.ADAPTIVE_ATR_PERCENTILE_ENABLED:
            if atr_percentile < 35.0:
                # Low volatility compression: tighter scalping targets
                sl_mult = 1.2
                tp_mult = 2.0
            elif atr_percentile > 70.0:
                # High volatility expansion: wider targets to ride runners
                sl_mult = 1.8
                tp_mult = 3.6
            else:
                sl_mult = config.ATR_SL_MULTIPLIER
                tp_mult = default_tp_mult
        else:
            sl_mult = config.ATR_SL_MULTIPLIER
            tp_mult = default_tp_mult

        is_crypto = any(c in symbol for c in ["BTC", "ETH", "SOL", "XRP"])

        if is_crypto:
            # For Crypto, calculate SL/TP directly from ATR price units or minimum spread clearance
            spread_dist = tick.ask - tick.bid
            if config.USE_DYNAMIC_ATR_SLTP and atr_value > 0:
                sl_dist = max(atr_value * sl_mult, spread_dist * 3.0)
            else:
                sl_dist = max(150.0, spread_dist * 3.0)
            tp_dist = sl_dist * (tp_mult / sl_mult)
            sl_pips = round(sl_dist / pip_size, 1)
            tp_pips = round(tp_dist / pip_size, 1)
            sl_offset = sl_dist
            tp_offset = tp_dist
        else:
            if config.USE_DYNAMIC_ATR_SLTP and atr_value > 0:
                atr_in_pips = atr_value / pip_size
                sl_pips = round(max(config.MIN_SL_PIPS, min(config.MAX_SL_PIPS, atr_in_pips * sl_mult)), 1)
                tp_pips = round(sl_pips * (tp_mult / sl_mult), 1)
            else:
                sl_pips = config.STATIC_STOP_LOSS_PIPS
                tp_pips = config.STATIC_TAKE_PROFIT_PIPS

            sl_offset = sl_pips * pip_size
            tp_offset = tp_pips * pip_size

        if signal == "BUY":
            entry_price = tick.ask
            sl_price = round(entry_price - sl_offset, digits)
            tp_price = round(entry_price + tp_offset, digits)
        elif signal == "SELL":
            entry_price = tick.bid
            sl_price = round(entry_price + sl_offset, digits)
            tp_price = round(entry_price - tp_offset, digits)
        else:
            return None

        lot = self.calculate_lot_size(acc["equity"], symbol=symbol, sl_pips=sl_pips)

        # Mathematical Expected Value (EV) Gatekeeper
        pip_dollar_value = self.connector.get_pip_dollar_value(symbol, lot)
        sl_usd = sl_pips * pip_dollar_value
        tp_usd = tp_pips * pip_dollar_value

        asset_type = "CRYPTO" if is_crypto else "FOREX"
        stats = self.journal.get_all_time_stats(asset_type=asset_type)
        if stats.get("total", 0) >= 5:
            win_prob = stats.get("win_rate", 60.0) / 100.0
        else:
            # Check trained model performance win rate first
            trained_model_file = os.path.join(os.path.dirname(__file__), "trained_models.json")
            trained_wr = None
            if os.path.exists(trained_model_file):
                try:
                    with open(trained_model_file, "r") as f:
                        trained_data = json.load(f)
                        perf = trained_data.get(symbol, {}).get("one_year_performance", {})
                        if perf.get("win_rate", 0) > 0:
                            trained_wr = perf["win_rate"] / 100.0
                except Exception:
                    pass
            if trained_wr is not None:
                win_prob = trained_wr
            else:
                win_prob = 0.55 if is_crypto else 0.60

        ev_usd, ev_ratio = QuantitativeEngine.calculate_expected_value(win_prob, tp_usd, sl_usd)

        if config.EXPECTED_VALUE_FILTER_ENABLED and ev_ratio < config.MIN_EV_RATIO:
            logger.warning(f"Mathematical EV too low: ${ev_usd:.2f} (Ratio {ev_ratio:.2f} < {config.MIN_EV_RATIO}). Entry rejected.")
            return None

        return {
            "entry": round(entry_price, digits),
            "sl": sl_price,
            "tp": tp_price,
            "sl_pips": sl_pips,
            "tp_pips": tp_pips,
            "lot": lot,
            "ev_usd": ev_usd,
            "ev_ratio": ev_ratio,
            "atr_pct": atr_percentile,
            "atr": atr_value
        }
