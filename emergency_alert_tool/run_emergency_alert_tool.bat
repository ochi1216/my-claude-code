@echo off
setlocal

rem emergency_alert_tool 起動用バッチファイル。
rem このファイルと同じフォルダに config.json を配置してから実行すること。

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python が見つかりません。Python がインストールされ、PATHが通っているか確認してください。
    pause
    exit /b 1
)

if not exist "venv" (
    echo [INFO] 仮想環境(venv)を作成します...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] 仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat

echo [INFO] 依存パッケージを確認・インストールします...
pip install -r requirements.txt

if not exist "config.json" (
    echo [ERROR] config.json が見つかりません。
    echo         config.example.json をコピーして config.json を作成し、
    echo         tenant_id / client_id / sender_upn / staff / supervisors 等を設定してください。
    pause
    exit /b 1
)

if "%EMERGENCY_ALERT_CLIENT_SECRET%"=="" (
    echo [WARN] 環境変数 EMERGENCY_ALERT_CLIENT_SECRET が設定されていません。
    echo        config.json の client_secret_env で別名を指定している場合は、
    echo        そちらの環境変数を事前に set しておいてください。
    echo        設定なしで続行しますが、メール送信(Microsoft Graph)は失敗します。
)

echo [INFO] emergency_alert_tool を起動します（終了する場合はこのウィンドウで Ctrl+C）。
python emergency_alert_tool_20260729_01.py --config config.json --mode web --port 5000

pause
