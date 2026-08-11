@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
cd /d "%~dp0"

echo [1] フルパスのpython.exeで呼び出します（修正後の本番と同じ方式）...
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE (
    echo ERROR: python.exe not found on PATH!
    pause
    exit /b 1
)
"%PYTHON_EXE%" check_suspend_lock.py
set "LOCKRC=!ERRORLEVEL!"
echo [2] 戻り値を確認します。 LOCKRC=[!LOCKRC!]

if "!LOCKRC!"=="1" (
    echo [3] SUSPENDED 分岐に入りました
) else (
    echo [3] 通常分岐に入りました。ここから先が本来Step1を呼ぶ場所です。
)

echo [4] ここまで到達すればテスト成功です。
pause
