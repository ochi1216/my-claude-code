@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
set PYTHONIOENCODING=utf-8

rem ========================================
rem Publish to iPhone (consolidate -> copy -> git push)
rem Version is tracked in Git, not in this file.
rem
rem What this does:
rem   1. Runs consolidated_html_summary_manager.py to regenerate
rem      _Consolidated_Manager.html from the current Summary folder.
rem   2. Copies that file into ..\youtube-summary-viewer\index.html
rem      (expected as a sibling folder to this one - same layout used
rem      when that repo was first cloned).
rem   3. git add / commit / push in youtube-summary-viewer, so the
rem      iPhone-facing GitHub Pages site picks up the update.
rem
rem Usage:
rem   publish_to_iphone.bat        ... interactive (pauses at the end)
rem   publish_to_iphone.bat auto   ... unattended (no pause)
rem
rem This intentionally does NOT decide the output path itself; it reads
rem the path back out of consolidated_html_summary_manager.py's own
rem "generated at:" message, so it always matches whatever config.json /
rem YT_SUMMARY_OUTPUT_DIR actually resolved to that run.
rem ========================================

cd /d "%~dp0"

set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE (
    echo ERROR: python.exe not found on PATH!
    goto :fail
)

set "VIEWER_DIR=%~dp0..\youtube-summary-viewer"
if not exist "!VIEWER_DIR!" (
    echo ERROR: youtube-summary-viewer folder not found: !VIEWER_DIR!
    echo         Expected as a sibling folder to this one ^(..\youtube-summary-viewer^).
    goto :fail
)

set "TMP_OUT=%TEMP%\publish_to_iphone_%RANDOM%.tmp"

echo =========================================================
echo [1/3] Consolidated HTML を生成します
echo =========================================================
"%PYTHON_EXE%" consolidated_html_summary_manager.py > "%TMP_OUT%" 2>&1
set "RC1=!ERRORLEVEL!"
type "%TMP_OUT%"
echo.

if not "!RC1!"=="0" (
    echo [ERROR] 統合HTML生成が失敗しました。終了コード: !RC1!
    del "%TMP_OUT%" >NUL 2>&1
    goto :fail
)

rem 出力先パスをここで決め打ちせず、スクリプト自身の成功メッセージから読み取る。
rem ("[Success] Consolidated HTML generated at: <path>" という1行を探す)
set "SRC_HTML="
for /f "usebackq delims=" %%D in (`"%PYTHON_EXE%" -c "import sys; t=open(sys.argv[1],encoding='utf-8',errors='replace').read(); m='Consolidated HTML generated at: '; i=t.find(m); print(t[i+len(m):].splitlines()[0].strip() if i>=0 else '')" "%TMP_OUT%"`) do set "SRC_HTML=%%D"
del "%TMP_OUT%" >NUL 2>&1

if not defined SRC_HTML (
    echo [ERROR] 生成先パスをスクリプトの出力から特定できませんでした。
    goto :fail
)
if not exist "!SRC_HTML!" (
    echo [ERROR] 生成されたはずのファイルが見つかりません: !SRC_HTML!
    goto :fail
)
echo   生成先: !SRC_HTML!
echo.

echo =========================================================
echo [2/3] youtube-summary-viewer へコピーします
echo =========================================================
copy /Y "!SRC_HTML!" "!VIEWER_DIR!\index.html" >NUL
if errorlevel 1 (
    echo [ERROR] コピーに失敗しました。
    goto :fail
)
echo   コピー完了: !VIEWER_DIR!\index.html
echo.

echo =========================================================
echo [3/3] Git commit / push します
echo =========================================================
pushd "!VIEWER_DIR!"

git pull > "%TMP_OUT%" 2>&1
type "%TMP_OUT%"
if errorlevel 1 (
    echo [ERROR] git pull に失敗しました。ネットワークやコンフリクトを確認してください。
    del "%TMP_OUT%" >NUL 2>&1
    popd
    goto :fail
)
del "%TMP_OUT%" >NUL 2>&1

git add index.html

git commit -m "update (publish_to_iphone.bat)" > "%TMP_OUT%" 2>&1
set "RC_COMMIT=!ERRORLEVEL!"
type "%TMP_OUT%"
findstr /C:"nothing to commit" "%TMP_OUT%" >NUL 2>&1
if not errorlevel 1 (
    echo   変更がないため、pushは不要です。
    del "%TMP_OUT%" >NUL 2>&1
    popd
    goto :done
)
del "%TMP_OUT%" >NUL 2>&1
if not "!RC_COMMIT!"=="0" (
    echo [ERROR] git commit に失敗しました。
    popd
    goto :fail
)

git push > "%TMP_OUT%" 2>&1
set "RC_PUSH=!ERRORLEVEL!"
type "%TMP_OUT%"
del "%TMP_OUT%" >NUL 2>&1
popd
if not "!RC_PUSH!"=="0" (
    echo [ERROR] git push に失敗しました。
    goto :fail
)

echo   push 完了。
echo.

:done
echo =========================================================
echo 完了しました。
echo iPhoneで https://ochi1216.github.io/youtube-summary-viewer/ を確認してください。
echo ^(反映まで数十秒かかることがあります^)
echo =========================================================
if /I not "%~1"=="auto" pause
exit /b 0

:fail
echo =========================================================
echo 失敗しました。上のメッセージを確認してください。
echo =========================================================
if /I not "%~1"=="auto" pause
exit /b 1

endlocal
