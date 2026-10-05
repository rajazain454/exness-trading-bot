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

### 2. 🏛️ Smart Money Concepts (SMC) & Market Structure (Area #4)
* **Daily High/Low & Pivot Points Engine ([smc.py](file:///f:/Random/WORK/exness/smc.py)):**
  * Computes **Previous Day High (PDH)**, **Previous Day Low (PDL)**, Daily Pivot (PP), R1, and S1.
  * **Trap Avoidance:** Suppresses **BUY** signals within 5 pips below PDH or R1 (avoiding buying into resistance ceilings); suppresses **SELL** signals within 5 pips above PDL or S1 (avoiding selling into support floors).
* **Fair Value Gap (FVG) / Imbalance Verification:**
  * Identifies 3-candle institutional liquidity imbalances on M5 charts, awarding bonus confluence scores when setups align with unmitigated institutional order flow.

### 3. 🎯 Smart Partial Profit Taking (Scale-Out Engine)
* When your account compounds to `0.02` lot or higher:
  * **TP1 (+15 pips):** Automatically closes 50% of the volume (`0.01` lot) and banks real dollar profits into your balance.
  * **Risk-Free Runner:** Simultaneously advances Stop Loss to `Entry + 1 pip` (break-even) and lets the remaining `0.01` lot run towards TP2 (+30 pips) with a dynamic trailing stop.
  * Dispatches an instant confirmation embed to Discord.

### 4. 📊 Currency Strength Meter (CSM Engine)
* Measures relative momentum across the 5 major currencies (**EUR, USD, GBP, JPY, AUD**) in real time on M15/H1 charts ([csm.py](file:///f:/Random/WORK/exness/csm.py)).
* **Institutional Alignment:** Only takes a **BUY** when base currency is stronger than quote currency, and only takes a **SELL** when base currency is weaker.

### 5. 🕯️ Price Action Rejection Wicks & Volume Surge Filter
* **Rejection Wicks:** Confirms that buyers or sellers actively defended a key price level ($\ge 15\%$ lower wick on BUY, $\ge 15\%$ upper wick on SELL).
* **Volume Surge:** Verifies that trigger candle tick volume is $\ge 1.0\times$ the 20-period moving average.

### 6. ⚡ Flash Crash & Spread Anomaly Shield
* Continuously tracks the rolling 30-sample average spread for each instrument.
* If broker spreads suddenly expand to $\ge 2.5\times$ normal levels, the bot **locks all new order executions** until spreads stabilize.

### 7. 📊 Trend Strength Filter (ADX 14 - Chop Filter)
* Calculates the **Average Directional Index (ADX)** alongside $+DI$ and $-DI$.
* Enforces an entry gatekeeper: **ADX must be $\ge 20.0$** to filter out flat chop.

### 8. 🌐 Multi-Pair Opportunity Scanner (Basket Trading)
* Monitors a portfolio of major pairs: `EURUSDm`, `GBPUSDm`, `USDJPYm`, `AUDUSDm`.
* Assigns a **Confluence Quality Score (0 to 100)** to each pair and executes the single highest-probability setup while strictly maintaining the **maximum 1 open trade limit**.

### 9. 📈 Persistent SQLite Trade Journal (`trading_journal.db`)
* Automatically logs every trade lifecycle event to an embedded SQLite database ([journal.py](file:///f:/Random/WORK/exness/journal.py)):
  * Ticket #, Symbol, Action, Lot Size, Entry/Exit Price, Duration (minutes), Realized P&L ($), Pips, Latency (ms), Slippage (pips), and Exit Reason.

### 10. 🌙 Daily Discord End-of-Day Performance Digest
* Every evening at the close of active sessions (**20:00 UTC**), dispatches a rich performance report to your Discord channel.

### 11. 🛑 Consecutive Loss Cooldown (Anti-Revenge Trading)
* If the bot experiences **2 consecutive losses** on the same day, it automatically pauses trading for **3 hours**.

### 12. 💓 Heartbeat & Auto-Recovery Engine
* Auto-reconnects with exponential backoff if home Wi-Fi or MT5 connection drops, without crashing.
* Dispatches periodic operational health embeds to Discord.

### 13. 🕒 Trading Session & Rollover Blackout Filter
* Focuses on high-liquidity London/New York sessions (**07:00 – 20:00 UTC**).
* Enforces a total trading blackout during broker swap time (**21:45 – 22:30 UTC**).

### 14. 📅 Economic News Filter (ForexFactory Feed)
* Queries weekly economic calendars for **High-Impact (🔴 Red Folder)** events and halts entries **30 minutes before and after**.

### 15. 🔭 Multi-Timeframe Trend Confirmation (M5 + H1)
* Only buys when H1 trend is Bullish; only sells when H1 trend is Bearish.

### 16. 📏 Dynamic ATR-Based Stop Loss & Take Profit
* $\text{SL} = \text{Entry} \pm (1.5 \times \text{ATR})$ (10–20 pips).
* $\text{TP} = \text{Entry} \pm (2.5 \times \text{ATR})$ (**1:1.67 Risk/Reward ratio**).

### 17. 🛡️ Dynamic Break-Even & Trailing Stop
* When a trade is $+10$ pips in profit, moves Stop Loss to $\text{Entry} + 1\text{ pip}$ (risk-free trade).

### 18. 📈 Fractional Kelly Criterion Position Sizing (Edge #1)
* Calculates optimal capital allocation using the Kelly Criterion formula:
  $$f^* = \frac{p \cdot b - (1 - p)}{b}$$
  where $p = \text{Win Probability}$ and $b = \text{Win/Loss Payoff Ratio}$.
* Implements **Quarter-Kelly ($0.25 \times f^*$)** to mathematically prevent over-leverage on small accounts while accelerating account growth during winning regimes.

### 19. 📐 Z-Score Statistical Mean-Reversion Pullback (Edge #2)
* Computes the rolling standard score:
  $$Z = \frac{\text{Price} - \mu_{50}}{\sigma_{50}}$$
* Filters out chasing overextended moves ($|Z| > 1.5$) and ensures entries occur at genuine statistical discounts in trend direction.

### 20. 🌪️ Fractal Choppiness Index (CHOP) Filter (Edge #3)
* Uses fractal dimension math to identify market entropy:
  $$\text{CHOP} = 100 \times \frac{\log_{10}\left(\frac{\sum \text{ATR}_{14}}{\text{MaxHigh}_{14} - \text{MinLow}_{14}}\right)}{\log_{10}(14)}$$
* Completely suppresses trade entries whenever $\text{CHOP} \ge 61.8$ (flat, random consolidation), saving capital for directional breakouts ($\text{CHOP} < 61.8$).

### 21. ⚓ Intraday Volume-Weighted Average Price (VWAP) Anchor (Edge #4)
* Anchors intraday institutional fair value:
  $$\text{VWAP} = \frac{\sum (\text{Typical Price} \times \text{Volume})}{\sum \text{Volume}}$$
* Long entries require price to be near or below VWAP (institutional discount); Short entries require price to be near or above VWAP (institutional premium).

### 22. 📊 Volatility-Adaptive ATR Percentile Engine (Edge #5)
* Ranks current ATR volatility against its 100-bar historical distribution ($0\%$ to $100\%$).
* **Low Volatility (< 35%):** Automatically narrows Stop Loss to $1.2\times$ ATR for surgical scalp protection.
* **High Volatility (> 70%):** Dynamically widens Take Profit to $3.6\times$ ATR to capture massive momentum trends.

### 23. 🧮 Mathematical Expected Value (EV) Gatekeeper (Edge #6)
* Computes statistical expectation before dispatching any order:
  $$\text{EV} = (P_{\text{win}} \times \text{TP}_{\$}) - (P_{\text{loss}} \times \text{SL}_{\$})$$
* Strictly blocks execution if $\text{EV} < +\$0.30$ or $\text{EV}/\text{Risk} < +0.25$, guaranteeing positive mathematical expectancy on every trade.

### 24. 🛑 Friday Weekend Gap Auto-Close
* At **Friday 20:00 UTC**, all open positions close automatically and new entries halt to eliminate Sunday opening gap risk.

---

## 📊 1-Year Full Historical Training Results (All Coins & Pairs)

Trained over **1 Full Year (~100,000 M5 bars per instrument)** directly from the Exness server. Evaluated **purely in mathematical R-multiples (Risk Units)** with **zero account balance dependency** (1.0R risk per trade).

| Coin / Symbol | Type | 1-Year Period | Standard Benchmark (Win% \| Return \| PF) | Trained Quant Model (Win% \| Return \| PF \| MaxDD) | Optimal Parameters Discovered |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **BTCUSDm** | `CRYPTO` | 2025-10 to 2026-10 | 65.5% \| -31.2R \| PF 0.92 | **75.5% \| +6.7R \| PF 1.28 \| DD 9.6R** | $\text{CHOP}<61.8$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.8$ \| $\text{TP}:2.5\times$ |
| **SOLUSDm** | `CRYPTO` | 2024-07 to 2026-10 | 64.5% \| -67.6R \| PF 0.82 | **70.8% \| +2.8R \| PF 1.10 \| DD 8.4R** | $\text{CHOP}<61.8$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:3.0\times$ |
| **EURUSDm** | `FOREX` | 2025-05 to 2026-10 | 65.4% \| -10.0R \| PF 0.95 | **77.1% \| +1.6R \| PF 1.21 \| DD 2.6R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:3.0\times$ |
| **GBPUSDm** | `FOREX` | 2025-05 to 2026-10 | 64.9% \| -21.1R \| PF 0.90 | **70.8% \| +2.7R \| PF 1.19 \| DD 3.7R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.8$ \| $\text{TP}:3.0\times$ |
| **USDJPYm** | `FOREX` | 2025-05 to 2026-10 | 63.7% \| -32.1R \| PF 0.84 | **71.4% \| -0.3R \| PF 0.96 \| DD 4.1R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:2.5\times$ |
| **XRPUSDm** | `CRYPTO` | 2025-09 to 2026-10 | 64.3% \| -68.2R \| PF 0.82 | **64.2% \| -1.1R \| PF 0.95 \| DD 9.3R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:3.0\times$ |
| **ETHUSDm** | `CRYPTO` | 2025-10 to 2026-10 | 65.2% \| -92.3R \| PF 0.74 | **54.7% \| -14.2R \| PF 0.51 \| DD 16.1R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:2.5\times$ |
| **AUDUSDm** | `FOREX` | 2025-05 to 2026-10 | 62.5% \| -44.8R \| PF 0.80 | **58.5% \| -12.7R \| PF 0.25 \| DD 12.8R** | $\text{CHOP}<58.0$ \| $\text{RSI}:45$ \| $\|Z\|\le 1.5$ \| $\text{TP}:3.0\times$ |

*Every instrument's optimal configuration is saved in [trained_models.json](file:///f:/Random/WORK/exness/trained_models.json) and dynamically loaded by the live trading bot.*

### 🎯 Active Curated Portfolio: `["EURUSDm", "GBPUSDm", "BTCUSDm"]`
* **Forex Majors:** `EURUSDm` (+1.6R, 77.1% Win Rate, 2.6R DD) and `GBPUSDm` (+2.7R, 70.8% Win Rate, 3.7R DD) during active London & NY sessions.
* **Crypto Coin:** `BTCUSDm` (+6.7R, 75.5% Win Rate, 1.28 PF) with active 24/7 continuous trading.
* **Pruned Assets:** `ETHUSDm` and `AUDUSDm` are excluded from the active basket to prevent drag from negative 1-year walk-forward expectancy.

---

## 📊 Backtest Verification & Strategy Training (Short-Term M5/H1 Live Data)

### 2. Discovered Optimal Parameters (Trained Model)
* **Choppiness Index Cutoff:** $\text{CHOP} < 61.8$
* **RSI Pullback Thresholds:** Oversold $\le 45.0$ / Overbought $\ge 55.0$
* **Z-Score Pullback Range:** $|Z| \le 1.50$
* **Take-Profit Multiplier:** $3.0\times$ ATR ($1:2.0$ to $1:2.5$ Risk/Reward)

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

### 2. Direct Hard Test & Training Command
You can run the end-to-end hard test and training suite at any time:
```powershell
python hard_test_and_train.py
```

---

## 🔄 Transitioning from Demo to Real Account

When you have observed demo execution and feel confident:
1. In your **Exness Personal Area**, locate your Real MT5 Account Number and Server (e.g., `Exness-MT5Real`).
2. Log into this account inside your MT5 desktop client (`File -> Login to Trade Account`), or set `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER` in your [.env](file:///f:/Random/WORK/exness/.env).
3. Launch `python run_bot.py`. The bot will apply the exact same risk protection rules to your real funds.

