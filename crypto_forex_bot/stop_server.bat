@echo off
title Stop Exness FastAPI Server
echo Stopping any running Uvicorn server processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Terminating PID %%a listening on port 8000...
    taskkill /F /PID %%a >nul 2>&1
)
echo FastAPI server stopped successfully.
pause
