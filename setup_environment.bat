@echo off
title Ledger Pro - Initial Setup & Installation
color 0A
echo ========================================================
echo   Ledger Pro Offline Accounting System - Setup
echo ========================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python 3.10+ was not found on your system!
    echo Please install Python 3.10 or higher from https://www.python.org
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/3] Installing required packages...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [WARNING] Package installation encountered an issue. Proceeding...
)

echo [2/3] Verifying database structure...
python run.py init

echo [3/3] Creating Desktop Shortcut...
call create_desktop_shortcut.bat

echo.
echo ========================================================
echo   Ledger Pro Setup Completed Successfully!
echo   You can now double-click "start_tally.bat" or the
echo   "Ledger Pro Offline Accounting" icon on your Desktop.
echo ========================================================
echo.
pause
