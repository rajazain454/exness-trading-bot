@echo off
title Exness Quantitative Trading Bot (Background 24/7)
cd /d "%~dp0"
echo ============================================================
echo Starting Exness Quantitative Trading Bot in Background...
echo ============================================================
start /B python bot.py > bot_output.log 2>&1
echo Bot is now running silently in the background!
echo All output is streamed to: bot_output.log
echo To stop the bot, run: stop_bot.bat
pause
