@echo off
rem One-time setup on a new Windows machine: creates .venv and installs everything.
rem Needs Python 3.10+ (https://www.python.org/downloads/ - tick "Add python.exe to PATH").
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
echo Creating virtual environment in .venv ...
%PY% -m venv .venv || goto :fail
".venv\Scripts\python.exe" -m pip install --upgrade pip
echo Installing PyTorch (CPU build) ...
".venv\Scripts\python.exe" -m pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :fail
echo Installing the remaining packages ...
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt || goto :fail
echo.
echo Setup complete. Run start.bat, then open http://localhost:8000
echo (FinBERT, about 440 MB, downloads automatically on the first run.)
goto :eof
:fail
echo Setup failed - see the messages above.
exit /b 1
