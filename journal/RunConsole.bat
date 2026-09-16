@echo off
cd /d "C:\Users\nx023836\Documents\PythonScripts\my-claude-code\journal"
"C:\Program Files\Python\python.exe" run_latest.py
if errorlevel 1 (
    pause
)
