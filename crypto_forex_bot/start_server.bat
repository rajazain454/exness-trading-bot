@echo off
title Exness FastAPI Quant Prediction Server (Port 8000)
cd /d "%~dp0"
echo ============================================================
echo Starting Exness FastAPI ML & Quant Prediction Engine...
echo Listening on: http://127.0.0.1:8000/predict
echo Connected EA: Octa_Hybrid_Demo_EA.mq5
echo ============================================================
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
pause
