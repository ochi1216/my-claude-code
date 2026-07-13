@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ── 同じフォルダ内の po_database_organizer_*.py のうち、
rem    ファイル名の並び順で最新（日付_連番が最大）のものを自動選択する ──
set "LATEST="
for /f "delims=" %%F in ('dir /b /a-d /o-n "po_database_organizer_*.py" 2^>nul') do (
    if not defined LATEST set "LATEST=%%F"
)

if not defined LATEST (
    echo [エラー] po_database_organizer_*.py が見つかりません。
    echo          このバッチファイルをスクリプトと同じフォルダに置いてください。
    pause
    exit /b 1
)

echo ============================================================
echo  PO Database Organizer を起動します
echo  実行ファイル: %LATEST%
echo ============================================================
echo.

if not exist config.json (
    echo [警告] config.json が見つかりません。
    echo          config.example.json をコピーして config.json を作成し、
    echo          tenant_id / client_id / site_host / site_path 等を
    echo          環境に合わせて設定してから再実行してください。
    echo.
    pause
    exit /b 1
)

rem ── python コマンドの存在確認（python が無ければ py ランチャーを試す） ──
set "PYCMD="
where python >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYCMD=py"
)
if not defined PYCMD (
    echo [エラー] python が見つかりません。Python をインストールし、PATHを通してください。
    pause
    exit /b 1
)

rem ── 必要ライブラリが未インストールなら requirements.txt から自動インストール ──
%PYCMD% -m pip show msal >nul 2>nul
if errorlevel 1 (
    echo [初回セットアップ] 必要なライブラリをインストールします...
    %PYCMD% -m pip install -r requirements.txt
    echo.
)

%PYCMD% "%LATEST%"

echo.
echo 終了しました。ウィンドウを閉じるには何かキーを押してください。
pause >nul
