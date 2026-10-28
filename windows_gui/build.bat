@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "BUILD_HOME=%LOCALAPPDATA%\RCBoatBuild\v2110"
if not exist "%BUILD_HOME%\venv\Scripts\python.exe" py -3 -m venv "%BUILD_HOME%\venv"
call "%BUILD_HOME%\venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not exist "%BUILD_HOME%\work" mkdir "%BUILD_HOME%\work"
if not exist "%BUILD_HOME%\spec" mkdir "%BUILD_HOME%\spec"
set "OUTPUT_DIR=%~dp0..\dist"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
rem Keep unrelated SDK DLLs (for example Poppler's ICU build) out of the Qt bundle.
rem Qt deliberately uses the Windows system ICU shim; PATH-first collection can
rem otherwise package an ABI-incompatible icuuc.dll and break QtGui at startup.
set "PATH=%BUILD_HOME%\venv\Scripts;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "RCBoatControl_ROS_v2.1.12" --icon "%CD%\assets\cat_boat_icon.ico" --add-data "%CD%\assets;assets" --paths "%CD%" --workpath "%BUILD_HOME%\work" --specpath "%BUILD_HOME%\spec" --distpath "%OUTPUT_DIR%" "%CD%\app.py"
exit /b %ERRORLEVEL%
