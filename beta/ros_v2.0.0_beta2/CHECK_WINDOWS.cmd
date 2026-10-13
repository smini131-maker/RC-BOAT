@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 2
set "PS_SCRIPT=%~dp0tools\windows\runner.ps1"
if not exist "%PS_SCRIPT%" (
  echo [FAIL] RC Boat files are incomplete: tools\windows\runner.ps1 is missing.
  echo Extract the entire source ZIP first. Do not run CMD from inside a ZIP preview.
  set "RESULT=3"
  goto finish
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [FAIL] Windows PowerShell is unavailable. Restore Windows PowerShell 5.1.
  set "RESULT=4"
  goto finish
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -Action CHECK_WINDOWS -Root "%~dp0."
set "RESULT=%ERRORLEVEL%"
:finish
echo.
if "%RESULT%"=="0" (echo [OK] Windows preflight completed.) else (echo [FAIL] Windows preflight exit code %RESULT%. Check the above advice and logs folder.)
if not defined RCBOAT_NO_PAUSE pause
exit /b %RESULT%
