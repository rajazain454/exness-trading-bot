# 🤖 MetaTrader 5 Expert Advisors (EAs)

This folder contains the compiled `.mq5` Expert Advisors for MetaTrader 5.

---

### 1. `Octa_Hybrid_Demo_EA.mq5` (Crypto & Forex Multi-Asset Bot)
* **What it trades**: `BTCUSDm`, `ETHUSDm`, `SOLUSDm`, `XRPUSDm` (or major Forex pairs).
* **Timeframe**: `M5` chart.
* **Magic Number**: `1001001`.
* **How it works**:
  * Offloads ML signal generation to the local FastAPI server (`http://127.0.0.1:8000/predict`).
  * Only requires attaching to **1 chart** in MT5 (e.g. `BTCUSDm`).
  * Automatically handles lot sizing, Stop Loss, Take Profit, and Discord alerts.
* **Requirements**: Python server must be running (`start_server.bat`).

---

### 2. `Gold_Institutional_Scalper_EA.mq5` (Dedicated Gold Scalper)
* **What it trades**: `XAUUSDm` (Gold) exclusively.
* **Timeframe**: `M5` chart.
* **Magic Number**: `777001`.
* **How it works**:
  * 100% self-contained in MQL5 (zero latency, no external server needed).
  * Automatically filters for London & NY session hours (08:00 - 16:00 UTC).
  * Enforces fast EMA 9/21 pullbacks with rejection wick verification.
  * Banks 50% profit at +1.0x ATR and moves Stop Loss to Break-Even + $0.20.

---

### 📁 How to Install into MetaTrader 5:
1. In MetaTrader 5, click **File** -> **Open Data Folder**.
2. Navigate to `MQL5` -> `Experts`.
3. Copy both `.mq5` files from this folder into `MQL5\Experts`.
4. In MT5 Navigator (`Ctrl + N`), right-click **Expert Advisors** -> **Refresh**.
