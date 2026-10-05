import MetaTrader5 as mt5
import logging
import time
from typing import Optional, Dict, Any, Tuple
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MT5Connector")

class MT5Connector:
    """Manages the connection, auto-reconnection, and interaction with Exness MetaTrader 5."""

    TIMEFRAMES = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    def __init__(self):
        self.connected = False
        self.account_info = None
        self.verified_symbols = {}

    def initialize(self) -> bool:
        """Connects to the MT5 terminal and verifies account status."""
        init_args = {}
        if config.MT5_PATH:
            init_args["path"] = config.MT5_PATH

        if not mt5.initialize(**init_args):
            logger.error(f"Failed to initialize MT5: {mt5.last_error()}")
            return False

        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            try:
                login_id = int(config.MT5_LOGIN)
                authorized = mt5.login(
                    login=login_id,
                    password=config.MT5_PASSWORD,
                    server=config.MT5_SERVER
                )
                if not authorized:
                    logger.error(f"MT5 login failed: {mt5.last_error()}")
                    return False
                logger.info(f"Successfully logged into Exness account {login_id} on {config.MT5_SERVER}")
            except Exception as e:
                logger.error(f"Error parsing MT5 login: {e}")
                return False

        acc = mt5.account_info()
        if acc is None:
            logger.error(f"Failed to fetch account info: {mt5.last_error()}")
            return False

        self.account_info = acc
        self.connected = True
        logger.info(
            f"Connected to MT5 - Account: {acc.login}, Server: {acc.server}, "
            f"Balance: ${acc.balance:.2f}, Leverage: 1:{acc.leverage}"
        )
        return True

    def ensure_connection(self) -> bool:
        """Verifies MT5 is responsive. If disconnected, automatically attempts reconnection with backoff."""
        term_info = mt5.terminal_info()
        if term_info is not None and term_info.connected:
            return True

        logger.warning("MT5 connection drop detected! Initiating auto-reconnect sequence...")
        for attempt in range(1, 4):
            wait_time = attempt * 3
            logger.info(f"Reconnection attempt {attempt}/3 in {wait_time}s...")
            time.sleep(wait_time)
            if self.initialize():
                logger.info("Auto-recovery successful: Connection restored.")
                return True

        logger.critical("Auto-recovery failed: Unable to re-establish connection to Exness MT5.")
        return False

    def verify_symbol(self, symbol_name: str) -> Optional[str]:
        """Resolves symbol name (handling 'm' suffix) and enables it in Market Watch."""
        if symbol_name in self.verified_symbols:
            return self.verified_symbols[symbol_name]

        candidates = [symbol_name]
        if not symbol_name.endswith("m"):
            candidates.append(symbol_name + "m")
        else:
            candidates.append(symbol_name[:-1])

        target_symbol = None
        for sym in candidates:
            s_info = mt5.symbol_info(sym)
            if s_info is not None:
                target_symbol = sym
                break

        if target_symbol is None:
            return None

        mt5.symbol_select(target_symbol, True)
        self.verified_symbols[symbol_name] = target_symbol
        return target_symbol

    def get_symbol_tick(self, symbol: str):
        """Fetches the latest tick."""
        return mt5.symbol_info_tick(symbol)

    def get_pip_size(self, symbol: str) -> float:
        """Returns the value of 1 pip in price terms."""
        info = mt5.symbol_info(symbol)
        if not info:
            return 0.0001
        if info.digits in [3, 5]:
            return info.point * 10
        return info.point

    def get_pip_dollar_value(self, symbol: str, lot: float = 0.01) -> float:
        """
        Calculates the real dollar value of 1 pip for the specified lot size.
        Uses MT5 broker tick specifications (trade_tick_value, trade_tick_size)
        to accurately support Forex majors, JPY crosses, Metals, and Crypto.
        """
        pip_size = self.get_pip_size(symbol)
        info = mt5.symbol_info(symbol)
        if not info:
            return round((lot / 0.01) * 0.10, 4)

        if info.trade_tick_size > 0 and info.trade_tick_value > 0:
            tick_value_per_lot = info.trade_tick_value / info.trade_tick_size
            pip_val = pip_size * tick_value_per_lot * lot
            return round(pip_val, 4)

        # Fallback for Crypto where 1 point = 1 USD on 1 contract
        if any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"]):
            contract_size = info.trade_contract_size if info.trade_contract_size > 0 else 1.0
            return round(pip_size * contract_size * lot, 4)

        return round((lot / 0.01) * 0.10, 4)

    def get_current_spread_pips(self, symbol: str) -> float:
        """Returns the current bid-ask spread in pips."""
        tick = self.get_symbol_tick(symbol)
        if not tick:
            return 999.0
        pip_size = self.get_pip_size(symbol)
        spread = (tick.ask - tick.bid) / pip_size
        return round(spread, 2)

    def get_rates(self, symbol: str, timeframe_str: str, count: int = 150):
        """Fetches historical candles."""
        tf = self.TIMEFRAMES.get(timeframe_str.upper(), mt5.TIMEFRAME_M5)
        return mt5.copy_rates_from_pos(symbol, tf, 0, count)

    def get_account_summary(self) -> Dict[str, Any]:
        """Refreshes and returns current account balance, equity, and margin."""
        acc = mt5.account_info()
        if not acc:
            return {}
        return {
            "login": acc.login,
            "server": acc.server,
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "free_margin": acc.margin_free,
            "margin_level": acc.margin_level,
            "leverage": acc.leverage,
            "currency": acc.currency,
            "trade_allowed": acc.trade_allowed and acc.trade_expert
        }

    def shutdown(self):
        """Safely disconnects from MT5."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 connection closed gracefully.")
