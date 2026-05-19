@echo off
REM Apex AI - Quick Setup Script (Windows)
REM Installs all dependencies for backend, web, and mobile frontends

echo.
echo ====================================
echo   Apex AI Setup Script v2.0
echo ====================================
echo.

REM Check Node.js
where node >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Node.js not found. Install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('node -v') do set NODE_VERSION=%%i
echo [OK] Node.js %NODE_VERSION%

REM Check Python
where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] Python not found. Install Python 3.8+
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo [OK] %PYTHON_VERSION%

echo.
echo -----------------------------------
echo  Installing dependencies
echo -----------------------------------
echo.

REM ===== Main Backend (apex_llm + Streamlit) =====
echo [1/4] Core Python backend...
pip install -q -r requirements.txt 2>nul
if errorlevel 1 (
    echo [WARN] Some core dependencies failed (non-fatal if API backend works)
) else (
    echo [OK] Core Python deps installed
)

REM ===== FastAPI Backend =====
echo [2/4] FastAPI backend server...
cd backend_api
pip install -q -r requirements.txt 2>nul
if errorlevel 1 (
    echo [FAIL] Backend API deps failed
    pause
    exit /b 1
) else (
    echo [OK] Backend API deps installed
)
cd ..

REM ===== Web Frontend =====
echo [3/4] React web frontend...
cd frontend-web
call npm install --silent 2>nul
if errorlevel 1 (
    echo [FAIL] Web frontend deps failed
    pause
    exit /b 1
) else (
    echo [OK] Web frontend deps installed
)
cd ..

REM ===== Mobile Frontend =====
echo [4/4] React Native mobile frontend...
cd frontend-mobile
call npm install --silent 2>nul
if errorlevel 1 (
    echo [FAIL] Mobile frontend deps failed
    pause
    exit /b 1
) else (
    echo [OK] Mobile frontend deps installed
)
cd ..

echo.
echo ====================================
echo  Setup Complete!
echo ====================================
echo.
echo Start the app:
echo.
echo   Terminal 1 - Backend API:
echo     cd backend_api ^&^& python -m uvicorn main:app --reload --port 8000
echo.
echo   Terminal 2 - Web Frontend:
echo     cd frontend-web ^&^& npm run dev
echo.
echo   Terminal 3 - Mobile (optional):
echo     cd frontend-mobile ^&^& npm start
echo.
echo   Access:
echo     Web:    http://localhost:5173
echo     API:    http://localhost:8000/docs
echo     Mobile: http://localhost:8081
echo.
pause
exit /b 0
