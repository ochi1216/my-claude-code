@echo off
rem Library_stock_summary_remover.bat
rem Moves generated HTML summaries (Library_new_stock_summary_*) that pile up
rem in the Summary folder to the Recycle Bin (not a permanent delete, so it
rem can still be restored if needed).

set "TARGET_DIR=C:\Users\nx023836\Nexperia\My Private - Documents\Summary"
set "PATTERN=Library_new_stock_summary_*"

if not exist "%TARGET_DIR%" (
    echo [ERROR] Folder not found: %TARGET_DIR%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName Microsoft.VisualBasic; $files = Get-ChildItem -LiteralPath '%TARGET_DIR%' -Filter '%PATTERN%' -File -ErrorAction SilentlyContinue; if (-not $files) { Write-Host '[INFO] No matching files found.' } else { foreach ($f in $files) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f.FullName, 'OnlyErrorDialogs', 'SendToRecycleBin') }; Write-Host ('[INFO] Moved ' + $files.Count + ' file(s) to the Recycle Bin.') }"

echo.
pause
