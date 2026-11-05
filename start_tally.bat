@echo off
title Ledger Pro - Offline Accounting System
color 0B
echo ========================================================
echo   Ledger Pro Offline Accounting System
echo   Double-Entry Accounting & Indian GST Compliance
echo ========================================================
echo.
echo Initializing environment...

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python was not found in PATH!
    echo Please install Python 3.10+ to run TallySoft.
    pause
    exit /b 1
)

echo Starting local server on http://127.0.0.1:5000...
start "" "http://127.0.0.1:5000"
python run.py serve

pause

