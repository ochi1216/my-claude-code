@echo off
rem Journal (LKPT / time management / action items) launcher.
rem
rem 2026-09-11: the folder path was hardcoded to
rem   C:\Users\nx023836\Documents\PythonScripts\Journal
rem which is the old standalone folder, so this file could not work from the
rem repository copy. Use %~dp0 (this file s own folder) instead, and call
rem "python" from PATH rather than an absolute interpreter path, to match the
rem convention used by the other run_*.bat files in this repository.
rem
rem run_latest.py always picks the newest daily_journal_yyyymmdd_NN.py, so this
rem file never needs editing when a new version is added.
cd /d "%~dp0"
python run_latest.py
pause
