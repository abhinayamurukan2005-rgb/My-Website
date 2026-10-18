@echo off
cd /d "%~dp0"
where python >nul 2>nul && (set PY=python) || (set PY=py)
echo Installing Flask (first time only)...
%PY% -m pip install flask
echo Starting BusMate... your browser will open in a few seconds.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:5050"
%PY% app.py
pause
