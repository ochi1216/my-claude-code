@echo off
chcp 932 >nul
setlocal enabledelayedexpansion

rem ==========================================================================
rem  weekly_pdf_diff 起動バッチ
rem
rem  同じフォルダ内にある weekly_pdf_diff_yyyymmdd_NN.py のうち、
rem  ファイル名（日付・連番）が最も新しいものを自動的に選んで実行する。
rem  新しいバージョンのファイルを同フォルダに追加するだけで、
rem  このバッチファイルを直すことなく最新版が起動される。
rem
rem  【文字化け対策】
rem  このファイルはShift_JIS(CP932)・BOMなしで保存すること。
rem  日本語版Windowsのコマンドプロンプトは既定でCP932のため、
rem  UTF-8で保存すると日本語部分が文字化けする。
rem  （UTF-8で運用したい場合は代わりに chcp 65001 を使い、
rem    このファイル自体もUTF-8(BOMなし)で保存すること。BOM付きで保存すると
rem    1行目の @echo off が正しく認識されずエラーになるので注意）
rem ==========================================================================

set "PYTHON=python"
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where %PYTHON% >nul 2>nul
if errorlevel 1 (
    echo エラー: python が見つかりません。
    echo Pythonをインストールし、PATHを通してから再実行してください。
    pause
    exit /b 1
)

set "LATEST="
for /f "delims=" %%F in ('dir /b /a-d "%SCRIPT_DIR%weekly_pdf_diff_????????_??.py" 2^>nul ^| sort') do (
    set "LATEST=%%F"
)

if not defined LATEST (
    echo エラー: %SCRIPT_DIR% 内に weekly_pdf_diff_yyyymmdd_NN.py が見つかりません。
    pause
    exit /b 1
)

echo ============================================================
echo  実行するバージョン: %LATEST%
echo ============================================================
echo.

if "%~1"=="" (
    echo 使い方: このバッチファイルへPDFファイルをドラッグ^&ドロップするか、
    echo         コマンドラインから引数としてPDFパスを渡してください。
    echo 例: run_weekly_pdf_diff.bat "C:\path\to\Hello_Ochi_San.pdf"
    echo.
)

"%PYTHON%" "%SCRIPT_DIR%%LATEST%" %*
set "EXITCODE=%ERRORLEVEL%"

echo.
if not "%EXITCODE%"=="0" (
    echo 処理がエラー終了しました。終了コード: %EXITCODE%
) else (
    echo 処理が正常に終了しました。
)

pause
exit /b %EXITCODE%
