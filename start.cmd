@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -I -S launch.py %*
) else (
    echo Run setup.ps1 to install the verified local environment first.
    exit /b 1
)
if errorlevel 1 (
    echo Could not start the app. Run setup.ps1 first.
    pause
)
