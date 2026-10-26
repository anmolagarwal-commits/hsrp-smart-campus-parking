@echo off
setlocal
cd /d "%~dp0.."
echo ==========================================
echo HSRP SMART PARKING - WINDOWS SERVER
echo ==========================================
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11+ and enable Add Python to PATH.
  pause
  exit /b 1
)
if not exist "templates\dashboard.html" (
  echo Missing templates\dashboard.html. Copy the package files into D:\HSRP_Parking first.
  pause
  exit /b 1
)
if not exist "static\style.css" (
  echo Missing static\style.css. Copy the package files into D:\HSRP_Parking first.
  pause
  exit /b 1
)
python -c "import flask" >nul 2>nul
if errorlevel 1 (
  echo Installing Flask...
  python -m pip install flask
)
echo Starting Flask. Keep this window open.
echo Dashboard: http://127.0.0.1:5000/dashboard
python server.py
pause
