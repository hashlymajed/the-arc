@echo off
title The Arc - Aldar Comms Platform
cd /d "%~dp0"

echo.
echo   The Arc - Aldar Comms Platform
echo   Starting up...
echo.

if not exist "venv" (
    echo   First run - setting up environment ^(takes ~2 min^)...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo   ERROR: Python 3.11+ not found.
        echo   Download from: https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    )
    call venv\Scripts\activate.bat
    pip install -q -r requirements.txt
    echo   Setup complete.
) else (
    call venv\Scripts\activate.bat
)

echo   Open: http://localhost:8000
echo   Press Ctrl+C to stop.
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

python app.py
pause
