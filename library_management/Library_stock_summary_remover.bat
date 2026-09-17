@echo off
rem Library_stock_summary_remover.bat
rem Summaryフォルダに溜まる Library_new_stock_summary_*（生成済みHTMLサマリ）を
rem まとめてごみ箱へ移動する（完全削除ではないため、誤操作時も復元できる）。

set "TARGET_DIR=C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
set "PATTERN=Library_new_stock_summary_*"

if not exist "%TARGET_DIR%" (
    echo [ERROR] フォルダが見つかりません: %TARGET_DIR%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName Microsoft.VisualBasic; $files = Get-ChildItem -LiteralPath '%TARGET_DIR%' -Filter '%PATTERN%' -File -ErrorAction SilentlyContinue; if (-not $files) { Write-Host '[INFO] 対象ファイルはありませんでした。' } else { foreach ($f in $files) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f.FullName, 'OnlyErrorDialogs', 'SendToRecycleBin') }; Write-Host ('[INFO] ' + $files.Count + ' 件をごみ箱に移動しました。') }"

echo.
pause
