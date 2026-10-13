@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 2
echo RC BOAT WINDOWS OPTIONAL SETUP
echo This helper is only needed when CHECK_WINDOWS.cmd reports a missing requirement.
echo Python 3.11, 3.12, or 3.13 x64 is supported; do not install another Python if 3.13 works.
echo Git is needed only for UPLOAD_GITHUB.cmd. OpenSSH is needed only for Jetson commands.
echo.
where winget.exe >nul 2>&1
if errorlevel 1 (
  echo [INFO] winget was not found. Manually install only the reported missing tool.
  echo [INFO] See docs folder for step-by-step instructions.
  set "RESULT=0"
  goto finish
)
choice /C PGSQ /N /M "Install (P)ython 3.11, (G)it, Open(S)SH, or (Q)uit? [P/G/S/Q]: "
if errorlevel 4 goto done
if errorlevel 3 goto ssh
if errorlevel 2 goto git
if errorlevel 1 goto python
:python
winget install --exact --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
set "RESULT=%ERRORLEVEL%"
goto finish
:git
winget install --exact --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
set "RESULT=%ERRORLEVEL%"
goto finish
:ssh
echo [INFO] Windows Settings - Optional Features - OpenSSH Client, or run as administrator:
echo Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
set "RESULT=0"
goto finish
:done
set "RESULT=0"
:finish
echo Reopen CMD after a PATH-changing installation, then run CHECK_WINDOWS.cmd again.
if not defined RCBOAT_NO_PAUSE pause
exit /b %RESULT%
