@echo off
setlocal
cd /d "%~dp0"
title RC Boat v1.6.0 Jetson Deployment
echo ==========================================================
echo RC Boat v1.6.0 - Jetson Deployment
echo ==========================================================
echo.
echo 1. Close RCBoatControl.exe
echo 2. REMOVE the propeller or disconnect propulsion power
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Deploy_Jetson_v1.6.0.ps1"
if errorlevel 1 (
    echo.
    echo DEPLOY_FAILED
    pause
    exit /b 1
)
echo.
echo DEPLOY_OK
pause
