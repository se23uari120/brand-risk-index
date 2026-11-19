@echo off
rem Starts the Brand Risk Index API + dashboard with the live news feed.
rem   USE_FINBERT=auto|true|false  (auto = use FinBERT if torch is installed)
rem   REFRESH_MINUTES=15           live re-fetch interval
rem   LOOKBACK_HOURS=48            news window
cd /d "%~dp0backend"
if "%REFRESH_MINUTES%"=="" set REFRESH_MINUTES=15
if "%LOOKBACK_HOURS%"=="" set LOOKBACK_HOURS=48
echo Dashboard: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs
"%~dp0.venv\Scripts\python.exe" api.py
