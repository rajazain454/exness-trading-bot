import sqlite3
import os
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger("TradeJournal")

class TradeJournal:
    """
    Persistent SQLite Trade Journal.
    Logs every trade lifecycle event, entry, exit, hold duration,
    slippage, latency (ms), and calculates daily/weekly performance analytics.
    """

    def __init__(self, db_path: str = "trading_journal.db"):
        self.db_path = db_path
        self._init_db()

    def _execute(self, query: str, params: tuple = (), fetch: bool = False, fetchall: bool = True):
        """Executes a query with strict resource disposal and connection closing."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch:
                res = cursor.fetchall() if fetchall else cursor.fetchone()
            else:
                conn.commit()
                res = None
            return res
        finally:
            conn.close()

    def _init_db(self):
        """Creates the trades table if it doesn't exist and migrates missing columns."""
        query = """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket INTEGER UNIQUE,
                symbol TEXT NOT NULL,
                signal TEXT NOT NULL,
                lot REAL NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                sl REAL,
                tp REAL,
                pips REAL,
                pnl_usd REAL,
                balance_after REAL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                hold_minutes INTEGER,
                outcome TEXT,
                close_reason TEXT,
                latency_ms REAL,
                slippage_pips REAL
            )
        """
        self._execute(query)

        # Migration helper for existing databases
        for col_name, col_type in [("latency_ms", "REAL"), ("slippage_pips", "REAL")]:
            try:
                self._execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass  # Already exists

    def record_entry(self, ticket: int, symbol: str, signal: str, lot: float, entry_price: float, sl: float, tp: float, latency_ms: float = 0.0, slippage_pips: float = 0.0):
        """Records a newly opened trade with execution latency and slippage."""
        now_str = datetime.utcnow().isoformat() + "Z"
        query = """
            INSERT OR REPLACE INTO trades (ticket, symbol, signal, lot, entry_price, sl, tp, entry_time, latency_ms, slippage_pips)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._execute(query, (ticket, symbol, signal, lot, entry_price, sl, tp, now_str, latency_ms, slippage_pips))
        logger.info(f"Journal: Trade #{ticket} ({symbol}) recorded. Latency: {latency_ms:.1f}ms | Slippage: {slippage_pips:.1f}p")

    def record_exit(self, ticket: int, exit_price: float, pips: float, pnl_usd: float, balance_after: float, close_reason: str):
        """Updates trade with exit price, realized profit, and duration."""
        exit_time = datetime.utcnow()
        exit_time_str = exit_time.isoformat() + "Z"

        row = self._execute("SELECT entry_time FROM trades WHERE ticket = ?", (ticket,), fetch=True, fetchall=False)
        hold_minutes = 0
        if row and row[0]:
            try:
                entry_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                hold_minutes = int((datetime.now(entry_dt.tzinfo) - entry_dt).total_seconds() / 60)
            except Exception:
                hold_minutes = 0

        outcome = "WIN" if pnl_usd >= 0 else "LOSS"

        query = """
            UPDATE trades
            SET exit_price = ?, pips = ?, pnl_usd = ?, balance_after = ?, exit_time = ?, hold_minutes = ?, outcome = ?, close_reason = ?
            WHERE ticket = ?
        """
        self._execute(query, (exit_price, pips, pnl_usd, balance_after, exit_time_str, hold_minutes, outcome, close_reason, ticket))
        logger.info(f"Journal: Trade #{ticket} exit finalized. PnL: ${pnl_usd:.2f} ({outcome})")

    def get_today_summary(self) -> Dict[str, Any]:
        """Calculates today's closed trades summary."""
        today_prefix = datetime.utcnow().strftime("%Y-%m-%d")
        query = """
            SELECT outcome, pnl_usd, pips FROM trades 
            WHERE exit_time LIKE ? AND exit_time IS NOT NULL
        """
        rows = self._execute(query, (f"{today_prefix}%",), fetch=True, fetchall=True)

        total = len(rows) if rows else 0
        if total == 0:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0, "total_pips": 0.0}

        wins = sum(1 for r in rows if r[0] == "WIN")
        losses = total - wins
        net_pnl = sum(r[1] for r in rows)
        total_pips = sum(r[2] for r in rows if r[2] is not None)
        win_rate = (wins / total) * 100.0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "net_pnl": round(net_pnl, 2),
            "total_pips": round(total_pips, 1)
        }

    def get_all_time_stats(self) -> Dict[str, Any]:
        """Calculates lifetime performance statistics."""
        query = "SELECT outcome, pnl_usd FROM trades WHERE exit_time IS NOT NULL"
        rows = self._execute(query, fetch=True, fetchall=True)

        total = len(rows) if rows else 0
        if total == 0:
            return {"total": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}

        wins = sum(1 for r in rows if r[0] == "WIN")
        losses = total - wins
        win_pnl = sum(r[1] for r in rows if r[1] > 0)
        loss_pnl = abs(sum(r[1] for r in rows if r[1] < 0))
        pf = (win_pnl / loss_pnl) if loss_pnl > 0 else 999.0
        net_pnl = sum(r[1] for r in rows)

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total) * 100.0, 1),
            "profit_factor": round(pf, 2),
            "net_pnl": round(net_pnl, 2)
        }
