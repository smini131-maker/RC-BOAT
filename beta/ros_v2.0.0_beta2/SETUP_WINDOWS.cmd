@echo off
setlocal
echo This will ask to install Python 3.11 and Git for Windows through winget.
echo Installation requires internet and approval.
choice /M "Proceed with prerequisite installation"
if errorlevel 2 goto done
where winget.exe >nul 2>&1
if errorlevel 1 (echo winget.exe is unavailable. Install Python 3.11 x64 and Git for Windows manually.&goto done)
winget install --exact --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 echo [WARNING] Python installer reported failure. Check output.
winget install --exact --id Git.Git --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 echo [WARNING] Git installer reported failure. Check output.
echo Reopen command prompt to refresh PATH before BUILD / UPLOAD.
:done
pause
