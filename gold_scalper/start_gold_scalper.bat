@echo off
title Exness Institutional Gold (XAUUSDm) Scalper Engine
cd /d "%~dp0\.."
echo ============================================================
echo Starting Institutional Gold (XAUUSDm) Scalper Bot...
echo London ^& NY Session Momentum Engine (08:00 - 16:00 UTC)
echo ============================================================
python -m gold_scalper.bot_gold
pause
