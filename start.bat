@echo off
rem Starts the NSE Brand Risk Monitor: dashboard + API + hourly live re-scoring.
rem   SENTIMENT=auto|finbert|lexicon   (auto = FinBERT if installed)
rem   REFRESH_MINUTES=60               live re-scoring interval
rem   LIVE_REFRESH=false               serve the stored results only
cd /d "%~dp0backend"
if "%REFRESH_MINUTES%"=="" set REFRESH_MINUTES=60
echo Dashboard: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/docs
"%~dp0.venv\Scripts\python.exe" api.py
