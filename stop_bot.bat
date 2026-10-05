@echo off
echo Stopping any running Exness bot processes...
taskkill /F /FI "WINDOWTITLE eq Exness Quantitative Trading Bot*" >nul 2>&1
wmic process where "commandline like '%%python bot.py%%'" delete >nul 2>&1
echo Done! All background bot processes stopped.
pause
