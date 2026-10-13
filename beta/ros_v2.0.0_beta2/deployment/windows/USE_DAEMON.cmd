@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "DEST=%~1"
if "%DEST%"=="" set "DEST=jetson@10.85.226.215"
call "%~dp0..\..\USE_DAEMON.cmd" -Destination "%DEST%"
exit /b %ERRORLEVEL%
