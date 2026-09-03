@echo off
REM ============================================================
REM  Start Fika Sync.bat
REM
REM  Double-click to open the application. The window running
REM  the server minimizes itself and the browser opens with the
REM  interface. Don't close that minimized window while using the
REM  app -- just minimize it or ignore it; to shut the server
REM  down completely, use "Stop Fika Sync.bat".
REM ============================================================

if "%~1"=="MIN" goto :RUN

REM --- Check that Python is present BEFORE minimizing, so the
REM     error can be shown if it's missing (otherwise the user
REM     would never see it) ---
where python >nul 2>nul
if %errorlevel%==0 (
    set "PYOK=1"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYOK=1"
    ) else (
        set "PYOK=0"
    )
)

if "%PYOK%"=="0" (
    echo Python was not found installed on this PC.
    echo.
    echo Run "INSTALL.bat" first ^(it's in the same folder^),
    echo or install Python from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0fika-sync\gui\app.py" (
    echo fika-sync\gui\app.py was not found
    echo Make sure you run this file from the project folder,
    echo without moving or renaming folders.
    pause
    exit /b 1
)

REM --- Relaunch minimized and close this visible window ---
start "Fika Sync" /min cmd /c "call "%~f0" MIN"
exit /b


:RUN
REM This part runs inside the already-minimized window.
title Fika Sync - Server (do not close this window)
cd /d "%~dp0fika-sync\gui"

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYCMD=python"
) else (
    set "PYCMD=py"
)

REM Opens the browser a couple of seconds after the server
REM starts, in a separate process so it doesn't block startup.
start "" cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:5000"

REM Starts the server. This command keeps running in this
REM minimized window -- that's what keeps it alive.
%PYCMD% app.py
