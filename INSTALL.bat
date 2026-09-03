@echo off
title Fika Sync - Installation
setlocal enabledelayedexpansion

echo ============================================
echo   Installing Fika Sync
echo ============================================
echo.

REM --- Detect the available Python command (python or py) ---
where python >nul 2>nul
if %errorlevel%==0 (
    set "PYCMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PYCMD=py"
    ) else (
        echo ERROR: Python was not found installed on this PC.
        echo.
        echo Download it from https://www.python.org/downloads/
        echo IMPORTANT: during installation, check the
        echo "Add python.exe to PATH" box before clicking Install.
        echo.
        echo After installing Python, run this file again.
        pause
        exit /b 1
    )
)

echo Python found ^(command: %PYCMD%^)
echo.

cd /d "%~dp0fika-sync\gui"
if not exist requirements.txt (
    echo ERROR: fika-sync\gui\requirements.txt was not found
    echo Make sure you run this file from the project folder
    echo without moving or renaming folders.
    pause
    exit /b 1
)

echo Installing dependencies ^(Flask, requests^)...
echo.
%PYCMD% -m pip install --upgrade pip >nul 2>nul
%PYCMD% -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo ============================================
    echo   ERROR during installation
    echo ============================================
    echo Check the message above. The most common reasons are:
    echo   - No internet connection.
    echo   - Python doesn't have pip installed correctly.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Installation complete
echo ============================================
echo.
echo You can now close this window and use
echo "Start Fika Sync.bat" to open the application.
echo.
pause
