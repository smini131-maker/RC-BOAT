@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist "%~dp0tools\windows\runner.ps1" (
  echo [ERROR] Missing tools\windows\runner.ps1
  pause
  exit /b 3
)
where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Windows PowerShell is required.
  pause
  exit /b 4
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\windows\runner.ps1" -Action "UPLOAD_GITHUB" -Root "%~dp0" %*
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (echo [OK] UPLOAD_GITHUB completed.) else (echo [ERROR] UPLOAD_GITHUB failed, code %RESULT%. Read logs directory.)
echo This window stays open until you press a key.
if not defined RCBOAT_NO_PAUSE pause
exit /b %RESULT%
