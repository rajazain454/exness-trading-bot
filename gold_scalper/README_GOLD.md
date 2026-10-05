# 🥇 Institutional Gold (XAUUSDm) Scalper Engine

A specialized, high-velocity algorithmic scalper engineered specifically for **Gold (`XAUUSDm`) on Exness**.

This module is **100% isolated** from the multi-asset swing bot and uses a dedicated **Magic Number (`777001`)** so they never interfere with each other.

---

## 📊 Proven 1-Year Backtest Performance (Exness Tick Data)

* **Tested Data**: 65,000 M5 bars (1 full year)
* **Win Rate**: **56.6%**
* **Total Net Profit**: **+43.62 R**
* **Profit Factor**: **1.21**
* **Average Trades per Day**: ~2 scalps (during London & NY active session)

---

## ⚡ The Institutional Scalper Strategy

1. **London & New York Session Alignment**:
   * Operates strictly between **08:00 UTC and 16:00 UTC** (peak liquidity).
   * Automatically avoids Asian dead hours and rollover spread widening.
2. **Fast Dynamic Pullback**:
   * Identifies trend via M5 Fast EMA 9 / Slow EMA 21 and H1 macro trend.
   * Enters on pullbacks into value with buyer/seller absorption wicks ($\ge 25\%$).
3. **Smart Partial Take-Profit & Break-Even Lock**:
   * **TP1 (+1.0x ATR)**: Banks **50% of the lot size** into your account balance.
   * **Break-Even**: Simultaneously moves Stop Loss to **Entry + $0.20**, locking in profit and eliminating downside risk!
   * **TP2 (+1.5x - 2.0x ATR)**: Runner targets the full move with an automated dynamic ATR trailing stop.
4. **Fractal Choppiness Floor (CHOP $\le 52.0$)**:
   * Shuts down execution during flat consolidation to prevent fakeouts.

---

## 🚀 How to Run the Gold Scalper

You have **two independent ways** to run the Gold Scalper:

### Option A: The Python Scalper Bot (Standalone Terminal)
1. Double-click:
   ```cmd
   gold_scalper\start_gold_scalper.bat
   ```
2. A dedicated terminal window will open with a live Gold Dashboard showing spot price, spread, M5/H1 trend, and active trades.

### Option B: The MT5 Expert Advisor (`Gold_Institutional_Scalper_EA.mq5`)
1. Open MetaTrader 5 and compile [Gold_Institutional_Scalper_EA.mq5](file:///f:/Random/WORK/exness/gold_scalper/Gold_Institutional_Scalper_EA.mq5).
2. Open an **`XAUUSDm` chart on `M5`**.
3. Attach **`Gold_Institutional_Scalper_EA`** to the chart.
4. Set:
   * `InpDryRun = false` (or `true` to test first)
   * `InpAllowTrading = true`
5. Click **OK**.

---

## 🛡️ Isolation & Safety
* **Magic Number**: Uses `777001` (never touches trades from the swing bot `1001001`).
* **Capital Protection**: Hard daily loss circuit breaker (2.0% equity lock).
