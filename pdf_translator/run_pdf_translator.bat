@echo off
chcp 65001 >nul 2>&1
rem PDF Gemini 翻訳ツール 起動用バッチファイル
rem このファイルをダブルクリックすると、初回のみ仮想環境(venv)を作成して
rem 依存パッケージをインストールし、ツールを起動します。
rem
rem 日本語Windowsのcmd.exeは既定でShift-JISコードページのため、UTF-8で保存された
rem このファイル内の日本語テキストを if (...) のような括弧ブロックの中に置くと、
rem マルチバイト文字の一部が )  などの制御文字として誤解釈され、構文エラーで
rem ウィンドウが一瞬で閉じることがある。これを避けるため、日本語を含む行は
rem すべて括弧ブロックの外（goto によるジャンプ先）に置いている。

setlocal enabledelayedexpansion
cd /d "%~dp0"

rem ファイル名は pdf_translator_yyyymmdd_NN.py の形式（バージョンアップ時も
rem 旧ファイルは残したまま新ファイルが追加される運用のため、名前順で並べ替えて
rem 最新（＝辞書順で最後）のファイルを自動的に起動対象にする。
set "TARGET_SCRIPT="
for /f "delims=" %%f in ('dir /b /o-n "pdf_translator_????????_??.py" 2^>nul') do (
    if not defined TARGET_SCRIPT set "TARGET_SCRIPT=%%f"
)
if not defined TARGET_SCRIPT goto :no_script

echo 起動対象: %TARGET_SCRIPT%

where python >nul 2>nul
if errorlevel 1 goto :no_python

if exist venv goto :venv_ready
echo 初回セットアップ: 仮想環境を作成しています...
python -m venv venv
if errorlevel 1 goto :venv_failed

:venv_ready
call venv\Scripts\activate.bat

echo 依存パッケージを確認しています...
pip install -q -r requirements.txt
if errorlevel 1 goto :pip_failed

if "%GEMINI_API_KEY%"=="" goto :warn_no_api_key

:run_tool
echo PDF Gemini 翻訳ツールを起動します...
python "%TARGET_SCRIPT%"
if errorlevel 1 goto :run_failed

goto :end

:no_script
echo [エラー] pdf_translator_yyyymmdd_NN.py の形式のファイルが見つかりません。
pause
exit /b 1

:no_python
echo [エラー] Python が見つかりません。
echo Python 3.9以上をインストールし、PATHに追加してから再実行してください。
pause
exit /b 1

:venv_failed
echo [エラー] 仮想環境の作成に失敗しました。
pause
exit /b 1

:pip_failed
echo [エラー] 依存パッケージのインストールに失敗しました。
pause
exit /b 1

:warn_no_api_key
echo.
echo [警告] 環境変数 GEMINI_API_KEY が設定されていません。
echo このまま起動すると起動直後にエラーになります。
echo 例: setx GEMINI_API_KEY "your-api-key"
echo 設定後は一度コマンドプロンプトを開き直す必要があります。
echo.
pause
goto :run_tool

:run_failed
echo.
echo [エラー] ツールの実行中に問題が発生しました。上記のメッセージを確認してください。
pause
goto :end

:end
endlocal
