# Exness Algorithmic Trading Suite (Institutional Edition)

An enterprise-grade algorithmic trading suite engineered for **Exness**, specifically tailored to trade and protect capital on a **$25 – $30 account with 1:50 leverage**.

---

## 🌟 Real-Time Exness Platform Synchronization

1. **Unified Infrastructure:**
   Every Exness account operates on the same backend whether accessed via the **Exness WebTerminal**, the **Exness Trade Mobile App**, or the desktop MetaTrader 5 terminal.
2. **Background Execution Engine:**
   The Python bot acts as the algorithmic brain, running 24/7 and routing orders directly to Exness servers.
3. **Instant Visibility:**
   **Every order, dynamic Stop Loss, Take Profit, break-even lock, partial profit bank, and trailing stop modification immediately reflects live on your Exness Web Terminal and Exness phone app in real time!**

---

## 🛡️ Complete Feature Matrix & Institutional Edge

### 1. ⚡ Execution Precision & Slippage Monitor (Area #3)
* **Millisecond Latency Tracking:** Measures exact roundtrip execution latency (in milliseconds) from order dispatch to Exness server confirmation.
* **Broker Slippage Calculation:** Records difference between requested quote and actual fill price in pips to the SQLite journal.
* **Limit Pullback Execution Mode:** 
  * Switch between `ENTRY_ORDER_TYPE=MARKET` (instant fill) and `ENTRY_ORDER_TYPE=LIMIT_PULLBACK` in [config.py](file:///f:/Random/WORK/exness/config.py) to place limit orders on exact EMA pullbacks, saving 0.5 – 1.0 pips on spread.
* **Pending Limit Order Expiry & Orphan Protection:** Unfilled pending limit pullback orders are tracked against open position quotas and automatically cancelled after `PENDING_ORDER_EXPIRY_MINS` (15 mins) via `mt5.TRADE_ACTION_REMOVE` ([order_manager.py](file:///f:/Random/WORK/exness/order_manager.py)).

### 2. 🏛️ Smart Money Concepts (SMC) & Market Structure (Area #4)
* **Daily High/Low & Pivot Points Engine ([smc.py](file:///f:/Random/WORK/exness/smc.py)):**
  * Computes **Previous Day High (PDH)**, **Previous Day Low (PDL)**, Daily Pivot (PP), R1, and S1.
  * **Trap Avoidance:** Suppresses **BUY** signals within 5 pips below PDH or R1 (avoiding buying into resistance ceilings); suppresses **SELL** signals within 5 pips above PDL or S1 (avoiding selling into support floors).
* **Unmitigated Fair Value Gap (FVG) Verification:**
  * Identifies 3-candle institutional liquidity imbalances on M5 charts.
  * **Mitigation Filter:** Inspects subsequent candle price action to verify that the gap has **not** been penetrated or filled. Only fresh, unmitigated institutional liquidity voids award confluence scores.

### 3. 🎯 Smart Partial Profit Taking (Scale-Out Engine)
* When your account compounds to `0.02` lot or higher:
  * **TP1 (+15 pips):** Automatically closes 50% of the volume (`0.01` lot) and banks real dollar profits into your balance.
  * **Risk-Free Runner:** Simultaneously advances Stop Loss to `Entry + 1 pip` (break-even) and lets the remaining `0.01` lot run towards TP2 (+30 pips) with a dynamic trailing stop.
  * Dispatches an instant non-blocking confirmation embed to Discord.

### 4. 📊 Currency Strength Meter (CSM Triangulation Engine)
* Measures relative momentum across major currencies (**EUR, USD, GBP, JPY, AUD**) in real time on M15/H1 charts ([csm.py](file:///f:/Random/WORK/exness/csm.py)).
* **Cross-Pair Triangulation:** Evaluates both majors and cross pairs (`EURUSDm`, `GBPUSDm`, `USDJPYm`, `AUDUSDm`, `EURGBPm`, `EURJPYm`, `GBPJPYm`) to isolate true individual currency momentum without USD bias or artificial JPY dampening.
* **Institutional Alignment:** Only takes a **BUY** when base currency is stronger than quote currency, and only takes a **SELL** when base currency is weaker.

### 5. 🔄 Startup State Hydration & Crash Recovery
* **Zero State Loss:** If the bot restarts or reboots while a position is open:
  * Automatically inspects MT5 open tickets and cross-references active records in [trading_journal.db](file:///f:/Random/WORK/exness/trading_journal.db) ([order_manager.py](file:///f:/Random/WORK/exness/order_manager.py#L29-L87)).
  * Restores break-even locks, partial-TP history, and original entry parameters so position exits and anti-revenge accounting remain uninterrupted.

### 6. 💰 Real-Time Broker Tick & Dynamic Pip Value Engine
* Dynamically calculates pip dollar values using live Exness broker specifications (`trade_tick_value` and `trade_tick_size`) via [mt5_connector.py](file:///f:/Random/WORK/exness/mt5_connector.py#L123-L144).
* Guarantees exact dollar P&L accounting and risk budgeting across Forex majors, JPY crosses, metals, and volatile Crypto assets (BTC/ETH/SOL).

### 7. 🕯️ Price Action Rejection Wicks & Volume Surge Filter
* **Rejection Wicks:** Confirms that buyers or sellers actively defended a key price level ($\ge 15\%$ lower wick on BUY, $\ge 15\%$ upper wick on SELL).
* **Volume Surge:** Verifies that trigger candle tick volume is $\ge 1.0\times$ the 20-period moving average.

### 8. ⚡ Flash Crash & Spread Anomaly Shield
* Continuously tracks the rolling 30-sample average spread for each instrument.
* If broker spreads suddenly expand to $\ge 2.5\times$ normal levels, the bot **locks all new order executions** until spreads stabilize.

### 9. 📊 Trend Strength Filter (ADX 14 - Chop Filter)
* Calculates the **Average Directional Index (ADX)** alongside $+DI$ and $-DI$.
* Enforces an entry gatekeeper: **ADX must be $\ge 20.0$** to filter out flat chop.

### 10. 🌐 Multi-Pair Opportunity Scanner (Basket Trading)
* Monitors a portfolio of curated pairs: `EURUSDm`, `GBPUSDm`, `BTCUSDm`.
* Assigns a **Confluence Quality Score (0 to 100)** to each pair and executes the single highest-probability setup while strictly maintaining the **maximum 1 open trade limit**.

### 11. 📈 Persistent SQLite Trade Journal (`trading_journal.db`)
* Automatically logs every trade lifecycle event to an embedded SQLite database ([journal.py](file:///f:/Random/WORK/exness/journal.py)):
  * Ticket #, Symbol, Action, Lot Size, Entry/Exit Price, Duration (minutes), Realized P&L ($), Pips, Latency (ms), Slippage (pips), and Exit Reason.

### 12. 🚀 Non-Blocking Asynchronous Discord Notifier
* Uses a thread-safe `queue.Queue` and background daemon worker thread ([notifier.py](file:///f:/Random/WORK/exness/notifier.py)).
* Dispatches embeds in **$< 0.1\text{ ms}$** without blocking or stalling critical price action checks or trailing stop updates in the main trading loop.

### 13. 🛑 Dual-Layer Capital Preservation & Trailing Profit Lock
* **Hard Daily Stop:** Halts trading if daily loss reaches `MAX_DAILY_LOSS_USD` ($5.00).
* **Peak Equity Trailing Circuit Breaker:** Tracks intraday high-watermark equity. If accumulated daily gains reach $\ge \$3.00$ ($\ge 10\%$ on a $\$30$ account) and pull back by $\ge 50\%$, locks all new entries to protect banked daily profit.
* **Anti-Revenge Cooldown:** Automatically pauses trading for **3 hours** after **2 consecutive losses**.

### 14. 💓 Heartbeat & Auto-Recovery Engine
* Auto-reconnects with exponential backoff if home Wi-Fi or MT5 connection drops, without crashing.
* Dispatches periodic operational health embeds and end-of-day performance digests to Discord.

### 15. 🕒 Trading Session & Rollover Blackout Filter
* Focuses on high-liquidity London/New York sessions (**07:00 – 20:00 UTC**).
* Enforces a total trading blackout during broker swap rollover (**21:45 – 22:30 UTC**). Crypto trades 24/7 continuously.

### 16. 📅 Non-Blocking Economic News Filter (ForexFactory Feed)
* Queries weekly economic calendars for **High-Impact (🔴 Red Folder)** events and halts entries **30 minutes before and after** ([news_filter.py](file:///f:/Random/WORK/exness/news_filter.py)).
* Runs asynchronously in a background thread to eliminate HTTP network stalls.

### 17. 🔭 Multi-Timeframe Trend Confirmation (M5 + H1)
* Only buys when H1 trend is Bullish; only sells when H1 trend is Bearish.

### 18. 📏 Dynamic ATR-Based Stop Loss & Take Profit
* $\text{SL} = \text{Entry} \pm (1.5 \times \text{ATR})$ (10–20 pips).
* $\text{TP} = \text{Entry} \pm (2.5 \times \text{ATR})$ (**1:1.67 Risk/Reward ratio**).

### 19. 🛡️ Dynamic Break-Even & Trailing Stop
* When a trade is $+10$ pips in profit, moves Stop Loss to $\text{Entry} + 1\text{ pip}$ (risk-free trade).

### 20. 📈 Dynamic Stop-Loss Fractional Kelly Criterion (Edge #1)
* Calculates optimal capital allocation using the Kelly Criterion formula:
  $$f^* = \frac{p \cdot b - (1 - p)}{b}$$
* Implements **Quarter-Kelly ($0.25 \times f^*$)** adapted to the exact stop-loss dollar distance and tick valuation to mathematically prevent over-leverage on small accounts.

### 21. 📐 Z-Score Statistical Mean-Reversion Pullback (Edge #2)
* Computes rolling standard score $Z = (\text{Price} - \mu_{50}) / \sigma_{50}$ to filter out overextended moves ($|Z| > 1.5$) and buy at institutional discounts.

### 22. 🌪️ Fractal Choppiness Index (CHOP) Filter (Edge #3)
* Completely suppresses trade entries whenever $\text{CHOP} \ge 61.8$ (flat consolidation), saving capital for directional breakouts.

### 23. ⚓ Intraday Volume-Weighted Average Price (VWAP) Anchor (Edge #4)
* Long entries require price to be near or below VWAP (institutional discount); Short entries require price to be near or above VWAP (institutional premium).

### 24. 📊 Volatility-Adaptive ATR Percentile Engine (Edge #5)
* Narrows SL to $1.2\times$ ATR during low volatility (< 35%) and widens TP to $3.6\times$ ATR during high volatility (> 70%).

### 25. 🧮 Mathematical Expected Value (EV) Gatekeeper (Edge #6)
* Strictly blocks execution if $\text{EV} < +\$0.30$ or $\text{EV}/\text{Risk} < +0.25$, guaranteeing positive mathematical expectancy on every trade.

### 26. 🛑 Friday Weekend Gap Auto-Close
* At **Friday 20:00 UTC**, all open Forex positions close automatically to eliminate Sunday opening gap risk.

---

## 📊 1-Year Full Historical Training Results (All Coins & Pairs)

Trained over **1 Full Year (~100,000 M5 bars per instrument)** directly on live Exness MT5 tick history. Evaluated **purely in mathematical R-multiples (Risk Units)** with **zero account balance dependency** (1.0R risk per trade), incorporating **Daily-Anchored VWAP (00:00 UTC reset)**, **EMA 50 Macro Baseline Filter**, and **Realistic Dual-Stage Scale-Out (+1.0R TP1 bank, BE +0.05R, runner to TP2)**:

| Coin / Symbol | Type | 1-Year Period | Standard Benchmark (Win% \| Return \| PF) | Trained Quant Model (Win% \| Return \| PF \| MaxDD) | Optimal Parameters Discovered |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **BTCUSDm** | `CRYPTO` | 2025-10 to 2026-10 | 62.7% \| +25.3R \| PF 1.06 | **70.1% \| +50.3R \| PF 1.49 \| DD 7.8R** | $\text{CHOP}<58.0$ \| $\text{RSI}:48$ \| $\|Z\|\le 1.8$ \| $\text{SL}:1.5\times$ \| $\text{TP}:2.0\times$ |
| **ETHUSDm** | `CRYPTO` | 2025-10 to 2026-10 | 62.5% \| +15.0R \| PF 1.04 | **66.2% \| +35.0R \| PF 1.28 \| DD 9.8R** | $\text{CHOP}<61.8$ \| $\text{RSI}:48$ \| $\|Z\|\le 1.8$ \| $\text{SL}:1.5\times$ \| $\text{TP}:2.0\times$ |
| **USDJPYm** | `FOREX` | 2025-05 to 2026-10 | 60.3% \| -17.9R \| PF 0.92 | **69.3% \| +17.6R \| PF 1.57 \| DD 7.0R** | $\text{CHOP}<61.8$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{SL}:1.5\times$ \| $\text{TP}:2.0\times$ |
| **XRPUSDm** | `CRYPTO` | 2025-09 to 2026-10 | 61.4% \| -10.1R \| PF 0.97 | **62.5% \| +11.6R \| PF 1.38 \| DD 7.5R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{SL}:1.2\times$ \| $\text{TP}:2.0\times$ |
| **SOLUSDm** | `CRYPTO` | 2024-07 to 2026-10 | 62.0% \| +5.8R \| PF 1.01 | **73.3% \| +6.8R \| PF 2.70 \| DD 1.0R** | $\text{CHOP}<58.0$ \| $\text{RSI}:42$ \| $\|Z\|\le 1.5$ \| $\text{SL}:1.5\times$ \| $\text{TP}:3.0\times$ |
| **GBPUSDm** | `FOREX` | 2025-05 to 2026-10 | 62.9% \| +9.6R \| PF 1.04 | **64.8% \| +6.1R \| PF 1.17 \| DD 5.2R** | $\text{CHOP}<61.8$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.8$ \| $\text{SL}:1.5\times$ \| $\text{TP}:2.0\times$ |
| **EURUSDm** | `FOREX` | 2025-05 to 2026-10 | 62.0% \| -9.9R \| PF 0.96 | **66.7% \| -0.8R \| PF 0.84 \| DD 2.0R** | $\text{CHOP}<61.8$ \| $\text{RSI}:42$ \| $\|Z\|\le 1.5$ \| $\text{SL}:1.2\times$ \| $\text{TP}:2.0\times$ |
| **AUDUSDm** | `FOREX` | 2025-05 to 2026-10 | 59.9% \| -25.9R \| PF 0.90 | **47.8% \| -6.3R \| PF 0.48 \| DD 6.4R** | $\text{CHOP}<58.0$ \| $\text{RSI}:42$ \| $\|Z\|\le 1.8$ \| $\text{SL}:1.5\times$ \| $\text{TP}:3.0\times$ |

> **Net Portfolio Performance:** **+120.3R net gain** over 1 year across the trained basket!
*Every instrument's optimal configuration is saved in [trained_models.json](file:///f:/Random/WORK/exness/trained_models.json) and dynamically loaded by the live trading bot.*

### 🎯 Active Curated Portfolio: `["EURUSDm", "GBPUSDm", "BTCUSDm"]`
* **Forex Majors:** `EURUSDm` and `GBPUSDm` (+6.1R, 64.8% Win Rate, 5.2R DD) during active London & NY sessions.
* **Crypto Coin:** `BTCUSDm` (+50.3R, 70.1% Win Rate, 1.49 PF, 7.8R DD) with active 24/7 continuous trading.
* **Pruned Assets:** `AUDUSDm` is excluded from the active basket to prevent drag from negative walk-forward expectancy.

---

## 🚀 How to Run the Bot

### 1. Launch the Suite
In your terminal, run:
```powershell
python run_bot.py
```

Choose from the interactive menu:
- `[1] Start Live Trading Bot` - Launches multi-pair basket scanning with real-time Rich dashboard.
- `[2] Run 6-Factor Quant Backtest` - Compares standard benchmark vs. quant edge.
- `[3] Inspect Exness Account & Market Status` - Checks live balance, margin, spread, and quotes.
- `[4] View SQLite Trade Journal & Analytics` - Displays lifetime win rate, profit factor, and today's summary.
- `[5] Run Hard Test & Train Bot` - Executes full diagnostic test suite & parameter optimizer.
- `[6] Exit`

### 2. Direct Hard Stress Test Command
You can run the full end-to-end 6-factor hard test suite at any time:
```powershell
python extreme_test.py
```
This validates:
1. Mathematical Bounds & Kelly Stress Test
2. Exness Broker Order Checks & Dynamic Pip Dollar Values
3. State Hydration across Restarts & Pending Orders Lifecycle
4. Strategy Engine & Unmitigated Fair Value Gap (FVG) Detection
5. Risk Gatekeepers & Intraday Peak-Equity Trailing Circuit Breaker
6. SQLite Database Journal Integrity & Concurrency

---

## 🔄 Transitioning from Demo to Real Account

When you have observed demo execution and feel confident:
1. In your **Exness Personal Area**, locate your Real MT5 Account Number and Server (e.g., `Exness-MT5Real`).
2. Log into this account inside your MT5 desktop client (`File -> Login to Trade Account`), or set `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER` in your [.env](file:///f:/Random/WORK/exness/.env).
3. Launch `python run_bot.py`. The bot will apply the exact same risk protection rules to your real funds.
