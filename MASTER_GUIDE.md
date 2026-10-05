# 🗺️ Master Project File Guide

The workspace has been organized into **four dedicated, self-contained directories**:

```text
exness/
│
├── 🤖 mt5_eas/              # META TRADER 5 EXPERT ADVISORS
│   ├── Octa_Hybrid_Demo_EA.mq5           # Crypto & Forex EA (Magic: 1001001)
│   ├── Gold_Institutional_Scalper_EA.mq5 # Gold Scalper EA (Magic: 777001)
│   └── README.md                         # Setup guide for MT5 charts
│
├── 🪙 crypto_forex_bot/     # BOT 1: CRYPTO & FOREX CONFLUENCE SUITE
│   ├── server.py                         # FastAPI ML server (port 8000)
│   ├── start_server.bat                  # Start FastAPI server
│   ├── stop_server.bat                   # Stop FastAPI server
│   ├── bot.py                            # Standalone Python swing bot
│   ├── start_bot_background.bat          # Run Python bot in background
│   ├── stop_bot.bat                      # Stop Python bot
│   ├── config.py                         # Account, risk & strategy settings
│   ├── strategy.py                       # Multi-timeframe trend & momentum strategy
│   ├── quant_engine.py                   # Kelly sizing, Z-Score, CHOP, VWAP
│   ├── trained_models.json               # 1-Year trained parameters (BTC, ETH, SOL, XRP)
│   ├── train_1year_all_coins.py          # 1-Year trainer for all coins
│   ├── backtester.py                     # Historical backtesting engine
│   ├── risk_manager.py                   # Capital preservation & lot sizing
│   ├── order_manager.py                  # Execution & slippage monitoring
│   ├── news_filter.py                    # ForexFactory high-impact news filter
│   ├── csm.py                            # Currency Strength Meter
│   ├── smc.py                            # Smart Money Concepts (FVG & daily pivots)
│   ├── mt5_connector.py                  # MT5 Python bridge
│   ├── notifier.py                       # Discord alerts
│   ├── journal.py                        # Trade journal logger
│   └── trading_journal.db                # SQLite database for logged trades
│
├── 🥇 gold_scalper/         # BOT 2: DEDICATED GOLD SCALPER SUITE
│   ├── Gold_Institutional_Scalper_EA.mq5 # Native MT5 Gold Scalper EA
│   ├── bot_gold.py                       # Standalone Python Gold Scalper
│   ├── start_gold_scalper.bat            # 1-Click launcher for Python Gold Scalper
│   ├── config_gold.py                    # Gold risk & London/NY session settings
│   ├── strategy_gold.py                  # Gold M5 EMA pullback & rejection wick strategy
│   ├── train_gold_1year.py               # 1-Year historical backtester for Gold
│   ├── gold_models.json                  # Proven 1-year stats (+43.62 R net gain, 56.6% WR)
│   └── README_GOLD.md                    # Full documentation for Gold scalping
│
├── 🧪 tests/                # UNIT & STRESS TESTS
│   └── extreme_test.py                   # Mathematical edge & formula stress tests
│
├── 🚀 Root Launchers
│   ├── start_crypto_server.bat           # 1-Click launcher to start port 8000 server
│   ├── stop_crypto_server.bat            # 1-Click launcher to stop port 8000 server
│   ├── .env                              # Exness credentials & Discord webhook
│   └── requirements.txt                  # Python dependencies
```

---

## 🎯 Which Files Do You Need to Touch?

### 🪙 Suite 1: Crypto & Forex Bot
1. **Server (AI Brain)**: Double-click **[start_crypto_server.bat](file:///f:/Random/WORK/exness/start_crypto_server.bat)** to keep the FastAPI engine running on port 8000.
2. **Execution**:
   - In MT5, attach **[mt5_eas/Octa_Hybrid_Demo_EA.mq5](file:///f:/Random/WORK/exness/mt5_eas/Octa_Hybrid_Demo_EA.mq5)** to `BTCUSDm, M5` (communicates with FastAPI server).
   - *OR* run the standalone Python swing engine via `crypto_forex_bot\start_bot_background.bat`.

---

### 🥇 Suite 2: Gold (XAUUSDm) Scalper (CHOOSE ONE OPTION ONLY)
> ⚠️ **DO NOT RUN BOTH AT THE SAME TIME** — They share symbol `XAUUSDm` and magic number `777001`.

* **Option A (⭐️ STRONGLY RECOMMENDED — Full 6-Quant Edge)**:
  - Double-click **[gold_scalper/start_gold_scalper.bat](file:///f:/Random/WORK/exness/gold_scalper/start_gold_scalper.bat)**.
  - Runs the full Python engine with CHOP, Z-score, ADX, VWAP, H1 macro trend, M1 micro-timing, and economic news blackout filter.
  - **Do NOT attach the Gold EA in MT5.**

* **Option B (Lightweight MT5 Fallback Only)**:
  - If you do not wish to run Python, attach **[mt5_eas/Gold_Institutional_Scalper_EA.mq5](file:///f:/Random/WORK/exness/mt5_eas/Gold_Institutional_Scalper_EA.mq5)** to `XAUUSDm, M5`.
  - Ensure the Python Gold Scalper terminal is closed.
