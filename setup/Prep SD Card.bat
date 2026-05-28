@echo off
:: BigRock SD Card Prep - double-click to run
:: Launches prep-sd-card.ps1 with admin privileges and keeps window open on error

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0prep-sd-card.ps1"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ==========================================
    echo   FAILED - see error above
    echo ==========================================
    pause
)
