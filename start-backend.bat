@echo off
echo ========================================
echo   Apex AI Backend Server Launcher
echo ========================================
echo.
echo Your local IP is: 192.168.1.40
echo Phone must be on same WiFi network.
echo In the mobile app Settings, set Backend URL to:
echo   http://192.168.1.40:8000/api
echo.
echo Starting backend on http://0.0.0.0:8000 ...
echo Press Ctrl+C to stop.
echo.
cd /d "%~dp0..\backend_api"
python main.py
pause
