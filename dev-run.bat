@echo off
rem Starts LunaTranslator from source with the repo's .venv.
rem Run dev-build.bat first (once, and again after C++ changes).
setlocal
set ROOT=%~dp0
if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo .venv not found. Run dev-build.bat first.
    pause
    exit /b 1
)
cd /d "%ROOT%src"
"%ROOT%.venv\Scripts\python.exe" -B LunaTranslator\main.py %*
if errorlevel 1 pause
