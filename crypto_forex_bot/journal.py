import sqlite3
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger("TradeJournal")

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_journal.db")

class TradeJournal:
    """
    Persistent SQLite Trade Journal.
    Logs every trade lifecycle event, entry, exit, hold duration,
    slippage, latency (ms), and calculates daily/weekly performance analytics.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def _execute(self, query: str, params: tuple = (), fetch: bool = False, fetchall: bool = True):
        """Executes a query with strict resource disposal and connection closing."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
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
        try:
            self._execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
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

    def record_entry(self, ticket: int, symbol: str, signal: str = "BUY", lot: float = 0.01, entry_price: float = 0.0, sl: float = 0.0, tp: float = 0.0, latency_ms: float = 0.0, slippage_pips: float = 0.0, **kwargs):
        """Records a newly opened trade with execution latency and slippage."""
        signal = kwargs.get("action", signal)
        lot = kwargs.get("lot_size", lot)
        now_str = datetime.now(timezone.utc).isoformat() + "Z"
        query = """
            INSERT OR REPLACE INTO trades (ticket, symbol, signal, lot, entry_price, sl, tp, entry_time, latency_ms, slippage_pips)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._execute(query, (ticket, symbol, signal, lot, entry_price, sl, tp, now_str, latency_ms, slippage_pips))
        logger.info(f"Journal: Trade #{ticket} ({symbol}) recorded. Latency: {latency_ms:.1f}ms | Slippage: {slippage_pips:.1f}p")

    # Backward compatibility alias
    log_entry = record_entry

    def record_exit(self, ticket: int, exit_price: float, pips: float = 0.0, pnl_usd: float = 0.0, balance_after: float = 0.0, close_reason: str = "TP/SL", **kwargs):
        """Updates trade with exit price, realized profit, and duration."""
        pnl_usd = kwargs.get("realized_pnl", pnl_usd)
        close_reason = kwargs.get("exit_reason", close_reason)
        exit_time = datetime.now(timezone.utc)
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

    # Backward compatibility alias
    log_exit = record_exit

    def get_trade(self, ticket: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single trade record as a dictionary."""
        query = "SELECT ticket, symbol, signal, lot, entry_price, exit_price, sl, tp, pips, pnl_usd, outcome, close_reason, latency_ms, slippage_pips FROM trades WHERE ticket = ?"
        row = self._execute(query, (ticket,), fetch=True, fetchall=False)
        if not row:
            return None
        return {
            "ticket": row[0],
            "symbol": row[1],
            "signal": row[2],
            "lot": row[3],
            "entry_price": row[4],
            "exit_price": row[5],
            "sl": row[6],
            "tp": row[7],
            "pips": row[8],
            "realized_pnl": row[9],
            "pnl_usd": row[9],
            "status": "CLOSED" if row[5] is not None else "OPEN",
            "outcome": row[10],
            "close_reason": row[11],
            "exit_reason": row[11],
            "latency_ms": row[12],
            "slippage_pips": row[13]
        }

    def get_today_summary(self) -> Dict[str, Any]:
        """Calculates today's closed trades summary."""
        today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query = """
            SELECT outcome, pnl_usd, pips FROM trades 
            WHERE exit_time LIKE ? AND exit_time IS NOT NULL
        """
        rows = self._execute(query, (f"{today_prefix}%",), fetch=True, fetchall=True)

        rows = rows or []
        total = len(rows)
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

    def get_all_time_stats(self, asset_type: Optional[str] = None) -> Dict[str, Any]:
        """Calculates lifetime performance statistics, optionally partitioned by asset_type ('CRYPTO' vs 'FOREX')."""
        if asset_type == "CRYPTO":
            query = """
                SELECT outcome, pnl_usd FROM trades 
                WHERE exit_time IS NOT NULL 
                AND (symbol LIKE '%BTC%' OR symbol LIKE '%ETH%' OR symbol LIKE '%SOL%' OR symbol LIKE '%XRP%')
            """
        elif asset_type == "FOREX":
            query = """
                SELECT outcome, pnl_usd FROM trades 
                WHERE exit_time IS NOT NULL 
                AND NOT (symbol LIKE '%BTC%' OR symbol LIKE '%ETH%' OR symbol LIKE '%SOL%' OR symbol LIKE '%XRP%')
            """
        else:
            query = "SELECT outcome, pnl_usd FROM trades WHERE exit_time IS NOT NULL"
        rows = self._execute(query, fetch=True, fetchall=True)

        rows = rows or []
        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_pnl": 0.0,
                "avg_win_usd": 0.0,
                "avg_loss_usd": 0.0
            }

        wins = sum(1 for r in rows if r[0] == "WIN")
        losses = total - wins
        win_pnl = sum(r[1] for r in rows if r[1] > 0)
        loss_pnl = abs(sum(r[1] for r in rows if r[1] < 0))
        pf = (win_pnl / loss_pnl) if loss_pnl > 0 else 999.0
        net_pnl = sum(r[1] for r in rows)
        avg_win = (win_pnl / wins) if wins > 0 else 0.0
        avg_loss = (loss_pnl / losses) if losses > 0 else 0.0

        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / total) * 100.0, 1),
            "profit_factor": round(pf, 2),
            "net_pnl": round(net_pnl, 2),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2)
        }
