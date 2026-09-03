@echo off
title Fika Sync - Stopping...

echo Looking for the Fika Sync server...
echo.

REM Attempt 1: by the window title set by "Start Fika Sync.bat"
taskkill /FI "WINDOWTITLE eq Fika Sync - Server*" /T /F >nul 2>nul
if %errorlevel%==0 (
    echo Server stopped.
    goto :END
)

REM Attempt 2: by port 5000, the default listening port
setlocal enabledelayedexpansion
set FOUND=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /PID %%P /F >nul 2>nul
    set FOUND=1
)

if "!FOUND!"=="1" (
    echo Server stopped ^(found via port 5000^).
) else (
    echo No running Fika Sync server was found.
    echo If you changed the default port, close it manually from
    echo Task Manager ^(look for "python.exe"^).
)

:END
echo.
pause
