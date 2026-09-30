@echo off
setlocal
cd /d "%~dp0windows_app"

if defined LOCALAPPDATA (
  set "VENV_DIR=%LOCALAPPDATA%\RCBoatControlBuild\venv"
) else (
  set "VENV_DIR=%CD%\.venv"
)

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found. Install Python 3.11 or newer x64 first.
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) and sys.maxsize.bit_length() >= 63 else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer x64 is required.
  exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  py -3 -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

python -m compileall -q app.py rcboat_gui
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean RCBoatControl.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete: %CD%\dist\RCBoatControl.exe
endlocal
