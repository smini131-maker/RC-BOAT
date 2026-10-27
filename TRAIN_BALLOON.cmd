@echo off
setlocal
cd /d "%~dp0"
set "TRAIN_ENV=%LOCALAPPDATA%\RCBoatBalloonTraining\v220\venv"
if not exist "%TRAIN_ENV%\Scripts\python.exe" (
  echo Install Python 3.12 and create the training environment using README_BALLOON.md.
  exit /b 1
)
"%TRAIN_ENV%\Scripts\python.exe" training\train_balloon.py %*
exit /b %ERRORLEVEL%
