@echo off
setlocal
echo RCBOAT WINDOWS CHECK
where powershell.exe
where py.exe
if not errorlevel 1 py -0p
where git.exe
where ssh.exe
echo.
echo Read docs\WINDOWS_빌드_업로드_문제해결.md
pause
