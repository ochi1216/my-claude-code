@echo off
setlocal

rem Launcher for emergency_alert_tool.
rem Place this file in the same folder as config.json before running.
rem NOTE: messages are kept in ASCII on purpose to avoid mojibake caused by
rem the Windows console codepage (e.g. Shift-JIS) misreading UTF-8 text.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found. Please install Python and make sure it is on PATH.
    pause
    exit /b 1
)

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo [INFO] Installing/checking dependencies...
pip install -r requirements.txt

if not exist "config.json" (
    echo [ERROR] config.json was not found.
    echo         Copy config.example.json to config.json and fill in
    echo         tenant_id / client_id / sender_upn / staff / supervisors, etc.
    pause
    exit /b 1
)

if "%EMERGENCY_ALERT_CLIENT_SECRET%"=="" (
    echo [WARN] Environment variable EMERGENCY_ALERT_CLIENT_SECRET is not set.
    echo        If config.json uses a different name via client_secret_env,
    echo        set that variable instead before running this script.
    echo        Continuing without it, but sending mail via Microsoft Graph will fail.
)

echo [INFO] Starting emergency_alert_tool. Press Ctrl+C in this window to stop.
python emergency_alert_tool_20260729_01.py --config config.json --mode web --port 5000

pause
