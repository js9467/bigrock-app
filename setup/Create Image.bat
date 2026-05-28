@echo off
:: BigRock SD Card Image Creator - double-click to run
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create Image.ps1"
if %ERRORLEVEL% neq 0 (
    echo.
    echo ==========================================
    echo   FAILED - see error above
    echo ==========================================
    pause
)
