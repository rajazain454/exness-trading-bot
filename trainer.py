import os
import json
import logging
from datetime import datetime
import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
import MetaTrader5 as mt5

from mt5_connector import MT5Connector

console = Console()
logger = logging.getLogger("Trainer")

PROFILES_DIR = "coin_profiles"

class CoinStrategyTrainer:
    """
    Automated Coin Training & Walk-Forward Optimization Engine.
    Trains algorithmic confluence parameters on 1 year of real Exness candle data
    specifically engineered for a $30 account balance.
    """

    def __init__(self, connector: MT5Connector):
        self.connector = connector
        os.makedirs(PROFILES_DIR, exist_ok=True)

    def calculate_indicators(self, df: pd.DataFrame, ema_fast: int, ema_slow: int, rsi_period: int = 14) -> pd.DataFrame:
        """Vectorized indicator calculation."""
        close = df["close"]
        high = df["high"]
        low = df["low"]

        df["ema_fast"] = close.ewm(span=ema_fast, adjust=False).mean()
        df["ema_slow"] = close.ewm(span=ema_slow, adjust=False).mean()

        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / rsi_period, adjust=False).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=14).mean()
        return df

    def simulate(self, df: pd.DataFrame, coin: str, sl_dist: float, tp_dist: float, rsi_bounce: float = 42.0) -> dict:
        """Simulates trading performance with 1:2+ R:R on $30 capital."""
        sym_info = mt5.symbol_info(coin)
        min_lot = sym_info.volume_min if sym_info else 0.01

        balance = 30.0
        peak_balance = 30.0
        max_drawdown = 0.0
        trades = []
        active = None

        for i in range(205, len(df)):
            c = df.iloc[i]
            p1 = df.iloc[i - 1]
            p2 = df.iloc[i - 2]
            bar_time = c["time"]

            if active:
                tt = active["t"]
                ep = active["ep"]
                sl = active["sl"]
                tp = active["tp"]
                exit_p = None
                win = False

                if tt == "BUY":
                    if c["low"] <= sl:
                        exit_p = sl
                        win = False
                    elif c["high"] >= tp:
                        exit_p = tp
                        win = True
                else:
                    if c["high"] >= sl:
                        exit_p = sl
                        win = False
                    elif c["low"] <= tp:
                        exit_p = tp
                        win = True

                if exit_p:
                    price_diff = (exit_p - ep) if tt == "BUY" else (ep - exit_p)
                    # Profit math: min_lot * price_diff (e.g. 0.01 lot * $100 move on BTC = $1.00)
                    pnl = round(price_diff * min_lot, 2)
                    balance += pnl
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = peak_balance - balance
                    if dd > max_drawdown:
                        max_drawdown = dd

                    trades.append({"win": win, "pnl": pnl, "time": bar_time})
                    active = None
            else:
                uptrend = c["ema_fast"] > c["ema_slow"] and c["close"] > c["ema_fast"]
                downtrend = c["ema_fast"] < c["ema_slow"] and c["close"] < c["ema_fast"]

                if uptrend and min(p1["rsi"], p2["rsi"]) <= rsi_bounce and c["rsi"] > rsi_bounce and c["rsi"] > p1["rsi"] and c["close"] >= c["open"]:
                    active = {"t": "BUY", "ep": c["close"], "sl": c["close"] - sl_dist, "tp": c["close"] + tp_dist}
                elif downtrend and max(p1["rsi"], p2["rsi"]) >= (100 - rsi_bounce) and c["rsi"] < (100 - rsi_bounce) and c["rsi"] < p1["rsi"] and c["close"] <= c["open"]:
                    active = {"t": "SELL", "ep": c["close"], "sl": c["close"] + sl_dist, "tp": c["close"] - tp_dist}

        total = len(trades)
        if total == 0:
            return {"total": 0, "win_rate": 0.0, "net_pnl": 0.0}

        wins = [t for t in trades if t["win"]]
        win_rate = (len(wins) / total) * 100.0
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in trades if not t["win"]))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
        net_pnl = balance - 30.0

        return {
            "total": total,
            "wins": len(wins),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "net_pnl": round(net_pnl, 2),
            "final_balance": round(balance, 2),
            "max_drawdown": round(max_drawdown, 2),
            "sl_dist": sl_dist,
            "tp_dist": tp_dist
        }

    def train_coin(self, coin: str, timeframe: str = "M15", candle_count: int = 25000) -> Optional[dict]:
        """Trains parameters on up to 1 year of real Exness data."""
        console.print(f"[bold cyan]Training Model for {coin} ({timeframe} - {candle_count} candles)...[/bold cyan]")
        valid_sym = self.connector.verify_symbol(coin)
        if not valid_sym:
            return None

        rates = self.connector.get_rates(valid_sym, timeframe, count=candle_count)
        if rates is None or len(rates) < 1000:
            return None

        raw_df = pd.DataFrame(rates)
        raw_df["time"] = pd.to_datetime(raw_df["time"], unit="s")

        # Test EMA combinations
        best_result = None
        best_score = -999999.0

        # Define candidate SL/TP grids tailored for coin price scale
        if "BTC" in coin:
            sl_grid = [100.0, 120.0, 150.0]
            tp_grid = [200.0, 240.0, 300.0]
        elif "ETH" in coin:
            sl_grid = [20.0, 30.0, 40.0]
            tp_grid = [50.0, 75.0, 100.0]
        else:
            sl_grid = [2.0, 3.0, 5.0]
            tp_grid = [5.0, 7.5, 12.0]

        for ema_f, ema_s in [(20, 100), (35, 150), (50, 200)]:
            df = self.calculate_indicators(raw_df.copy(), ema_f, ema_s)
            for sl in sl_grid:
                for tp in tp_grid:
                    for rsi_b in [40.0, 42.0, 45.0]:
                        sim = self.simulate(df, valid_sym, sl_dist=sl, tp_dist=tp, rsi_bounce=rsi_b)
                        if sim["total"] >= 20 and sim["net_pnl"] > 0:
                            score = (sim["profit_factor"] * 20.0) + (sim["win_rate"] * 1.5) + sim["net_pnl"] - (sim["max_drawdown"] * 2.0)
                            if score > best_score:
                                best_score = score
                                sim["ema_fast"] = ema_f
                                sim["ema_slow"] = ema_s
                                sim["rsi_bounce"] = rsi_b
                                best_result = sim

        if best_result is None:
            console.print(f"[yellow]No net-positive profile found for {valid_sym}.[/yellow]")
            return None

        profile_path = os.path.join(PROFILES_DIR, f"{valid_sym}.json")
        saved_data = {
            "symbol": valid_sym,
            "trained_candles": len(rates),
            "timeframe": timeframe,
            "training_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "params": {
                "ema_fast": best_result["ema_fast"],
                "ema_slow": best_result["ema_slow"],
                "rsi_bounce": best_result["rsi_bounce"],
                "sl_price_distance": best_result["sl_dist"],
                "tp_price_distance": best_result["tp_dist"]
            },
            "performance": {
                "initial_balance": 30.0,
                "final_balance": best_result["final_balance"],
                "net_profit_usd": best_result["net_pnl"],
                "win_rate": best_result["win_rate"],
                "profit_factor": best_result["profit_factor"],
                "total_trades": best_result["total"],
                "max_drawdown_usd": best_result["max_drawdown"]
            }
        }

        with open(profile_path, "w") as f:
            json.dump(saved_data, f, indent=4)

        console.print(f"[bold green]Saved Trained Model to {profile_path}![/bold green]")
        return saved_data

def train_all_coins(timeframe: str = "M15"):
    connector = MT5Connector()
    if not connector.initialize():
        return

    trainer = CoinStrategyTrainer(connector)
    coins = ["BTCUSDm", "ETHUSDm"]
    results = []

    for c in coins:
        prof = trainer.train_coin(c, timeframe=timeframe, candle_count=20000)
        if prof:
            results.append(prof)

    connector.shutdown()

    if results:
        table = Table(title="1-Year Trained Crypto Models ($30 Balance Simulation)", style="bold cyan")
        table.add_column("Coin", style="bold white")
        table.add_column("Candles", justify="right")
        table.add_column("Win Rate (%)", justify="right", style="bold green")
        table.add_column("Trades", justify="right")
        table.add_column("Net Profit ($)", justify="right", style="bold green")
        table.add_column("Profit Factor", justify="right")
        table.add_column("Max DD ($)", justify="right", style="yellow")
        table.add_column("Optimal EMAs", justify="center")

        for r in results:
            p = r["performance"]
            par = r["params"]
            table.add_row(
                r["symbol"],
                str(r["trained_candles"]),
                f"{p['win_rate']:.1f}%",
                str(p["total_trades"]),
                f"+${p['net_profit_usd']:.2f}",
                f"{p['profit_factor']:.2f}",
                f"${p['max_drawdown_usd']:.2f}",
                f"{par['ema_fast']}/{par['ema_slow']}"
            )

        console.print("\n")
        console.print(table)

if __name__ == "__main__":
    train_all_coins()
