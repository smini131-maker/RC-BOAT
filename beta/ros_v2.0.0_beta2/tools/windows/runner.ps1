param(
 [ValidateSet('CHECK_WINDOWS','BUILD_GUI','UPLOAD_GITHUB','CHECK_BACKEND','CHECK_ROS','DEPLOY_ROS','INSTALL_ROS','USE_ROS','USE_DAEMON')]
 [string]$Action,
 [string]$Root,
 [string]$Destination = 'jetson@10.85.226.215'
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Set-StrictMode -Version Latest
$Root = (Resolve-Path -LiteralPath $Root).Path
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("{0}_{1}.log" -f $Action,(Get-Date -Format yyyyMMdd_HHmmss))
$transcript = $false
function Check([bool]$ok,[string]$msg){if (-not $ok){throw $msg}}
function Run([string]$exe,[string[]]$arguments){
 Write-Host ('>> ' + $exe + ' ' + ($arguments -join ' '))
 & $exe @arguments
 $rc=$LASTEXITCODE
 if ($null -eq $rc){$rc=0}
 if ($rc -ne 0){throw "$exe exited with error code $rc"}
}
function CmdPath([string]$name){
 $c=Get-Command $name -ErrorAction SilentlyContinue
 Check ($null -ne $c) "$name not found. Install it, reopen this window, and retry."
 return $c.Source
}
function Resolve-RCBoatPython {
 # Inspect optional executables silently. Supports 3.11-3.13 64-bit Python.
 $code = "import sys; ok=(3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize > 2**32; print('RCBoat Python:',sys.version.split()[0],'x64' if sys.maxsize > 2**32 else 'x86'); sys.exit(0 if ok else 4)"
 if (-not [string]::IsNullOrWhiteSpace($env:RCBOAT_PYTHON)) {
   $item = Get-Item -LiteralPath $env:RCBOAT_PYTHON -ErrorAction SilentlyContinue
   Check ($null -ne $item) "RCBOAT_PYTHON does not exist: $env:RCBOAT_PYTHON"
   & $item.FullName -c $code | Out-Null
   Check ($LASTEXITCODE -eq 0) 'RCBOAT_PYTHON must be Python 3.11-3.13 x64.'
   return @{ Exe=$item.FullName; Prefix=@() }
 }
 $launcher=Get-Command py.exe -ErrorAction SilentlyContinue
 if ($launcher) {
   $listed=@(& $launcher.Source -0p 2>$null)
   if ($LASTEXITCODE -eq 0) {
     foreach($ver in @('3.11','3.12','3.13')) {
       if (@($listed | Where-Object { $_ -match ('(?<![0-9])3\.'+$ver.Substring(2)+'(?![0-9])') }).Count -gt 0) {
         & $launcher.Source ('-'+$ver) -c $code | Out-Null
         if ($LASTEXITCODE -eq 0) { return @{ Exe=$launcher.Source; Prefix=@('-'+$ver) } }
       }
     }
   }
 }
 $python=Get-Command python.exe -ErrorAction SilentlyContinue
 if ($python) {
   & $python.Source -c $code | Out-Null
   if ($LASTEXITCODE -eq 0) { return @{ Exe=$python.Source; Prefix=@() } }
 }
 return $null
}
function Report-Tool([string]$name,[string]$usage){
 $found=Get-Command $name -ErrorAction SilentlyContinue
 if ($found){Write-Host "[OK] $name : $($found.Source)"}
 else {Write-Host "[OPTIONAL] $name is absent. Needed only for $usage."}
}
try {
 Start-Transcript -LiteralPath $LogFile -Force -ErrorAction Stop | Out-Null
 $transcript=$true
 Write-Host "RCBoat ROS v2.0.0-beta.2 | $Action"
 Write-Host "Full log: $LogFile"
 if ($Action -eq 'CHECK_WINDOWS') {
   Write-Host '[OK] Windows PowerShell runner is working; source folder extracted.'
   $py=Resolve-RCBoatPython
   Check ($null -ne $py) 'No supported Python 3.11/3.12/3.13 x64 found. The prebuilt EXE does not require Python. For a local build, install supported x64 Python or use SETUP_WINDOWS.cmd.'
   Write-Host "[OK] Python available for local GUI build: $($py.Exe) $($py.Prefix -join ' ')"
   Report-Tool 'git.exe' 'UPLOAD_GITHUB.cmd (not needed to run EXE or build it)'
   Report-Tool 'ssh.exe' 'CHECK_BACKEND / USE_ROS / other remote Jetson operations'
   Report-Tool 'scp.exe' 'DEPLOY_ROS / INSTALL_ROS remote transfers'
   Report-Tool 'winget.exe' 'optional prerequisite installation'
   Write-Host '[OK] Windows environment check passed. No install or SSH action was performed.'
 } elseif ($Action -eq 'BUILD_GUI') {
   $py=Resolve-RCBoatPython
   Check ($null -ne $py) 'No supported Python 3.11/3.12/3.13 x64 found. Use CHECK_WINDOWS.cmd for diagnosis.'
   $PythonExe=$py.Exe; $PythonPre=$py.Prefix
   $AppDir = Join-Path $Root 'windows_gui'
   Check (Test-Path -LiteralPath (Join-Path $AppDir 'app.py')) 'windows_gui/app.py not found. Extract the entire ZIP.'
   # PySide6 has very deep QML paths. Installing inside a nested Downloads ZIP
   # can exceed the Windows MAX_PATH limit (260 chars). Always use SHORT paths.
   $BuildHome=Join-Path $env:LOCALAPPDATA 'RCBoatBuild\ros-beta2'
   $PyTag=(& $PythonExe @($PythonPre + @('-c',"import sys;print(str(sys.version_info.major)+str(sys.version_info.minor))")))
   Check ($LASTEXITCODE -eq 0) 'Failed to determine Python version.'
   $Venv=Join-Path $BuildHome ('venv'+$PyTag)
   $Exe=Join-Path $Venv 'Scripts\python.exe'
   $Stage=Join-Path $BuildHome 'stage'
   $Spec=Join-Path $BuildHome 'spec'
   $Work=Join-Path $BuildHome 'work'
   $Dist=Join-Path $AppDir 'dist'
   foreach($folder in @($BuildHome,$Stage,$Spec,$Work,$Dist)){
     New-Item -ItemType Directory -Force -Path $folder | Out-Null
   }
   Write-Host '[INFO] MAX_PATH safe build: virtualenv and PyInstaller work folders use short paths.'
   Write-Host "[INFO] Short virtualenv: $Venv"
   if(Test-Path (Join-Path $AppDir '.venv')){
     Write-Host '[INFO] Old incomplete source .venv ignored; no need to delete it.'
   }
   Copy-Item -LiteralPath (Join-Path $AppDir 'app.py') -Destination (Join-Path $Stage 'app.py') -Force
   Copy-Item -LiteralPath (Join-Path $AppDir 'telemetry_graph.py') -Destination (Join-Path $Stage 'telemetry_graph.py') -Force
   $AssetSource=Join-Path $AppDir 'assets'
   Check (Test-Path -LiteralPath $AssetSource) 'Missing assets folder. Re-extract full source.'
   $AssetStage=Join-Path $Stage 'assets'
   New-Item -ItemType Directory -Force -Path $AssetStage | Out-Null
   Copy-Item -Path (Join-Path $AssetSource '*') -Destination $AssetStage -Force
   Push-Location $Stage
   try {
     if(-not (Test-Path -LiteralPath $Exe)){
       Run $PythonExe ($PythonPre + @('-m','venv',$Venv))
     }
     Run $Exe @('-m','pip','--version')
     Run $Exe @('-m','pip','install','--disable-pip-version-check','-r',(Join-Path $AppDir 'requirements.txt'))
     Run $Exe @('-c',"import PySide6.QtWidgets,paramiko,PyInstaller;print('GUI dependencies OK')")
     Run $Exe @('-m','unittest','discover','-s',(Join-Path $Root 'tests'),'-v')
     Run $Exe @('app.py','--smoke-test')
     $Name='RCBoatControl_ROS_v2.0.0-beta.2'
     $Options=@('-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
                '--workpath',$Work,'--distpath',$Dist,'--specpath',$Spec,
                '--add-data',($AssetStage+';assets'),'--name',$Name)
     if(Test-Path -LiteralPath (Join-Path $AssetStage 'cat_boat_icon.ico')){
       $Options+=@('--icon',(Join-Path $AssetStage 'cat_boat_icon.ico'))
     }
     Run $Exe ($Options + @('app.py'))
     $Artifact=Join-Path $Dist ($Name+'.exe')
     Check (Test-Path -LiteralPath $Artifact) "Build succeeded but EXE missing: $Artifact"
     Check ((Get-Item -LiteralPath $Artifact).Length -gt 100000) 'EXE size unexpectedly small'
     $SmokeScript="import os,subprocess,sys; env=dict(os.environ); env['QT_QPA_PLATFORM']='offscreen'; rc=subprocess.run([sys.argv[1],'--smoke-test'],env=env,timeout=120).returncode; sys.exit(rc)"
     Run $Exe @('-c',$SmokeScript,$Artifact)
     Write-Host "BUILT FILE: $Artifact"
     if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
       $Digest=(Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash
     } else {
       # Get-FileHash may not be available in restricted Windows PowerShell hosts.
       $HashAlgorithm=[System.Security.Cryptography.SHA256]::Create()
       try {
         $Stream=[System.IO.File]::OpenRead($Artifact)
         try { $HashBytes=$HashAlgorithm.ComputeHash($Stream) }
         finally { $Stream.Dispose() }
       } finally { $HashAlgorithm.Dispose() }
       $Digest=[System.BitConverter]::ToString($HashBytes).Replace('-','')
     }
     Write-Host "SHA256: $Digest"
     ($Digest+' *'+$Name+'.exe') | Set-Content -LiteralPath (Join-Path (Split-Path -Parent $Artifact) 'SHA256SUMS.txt') -Encoding ASCII
     Write-Host 'Windows GUI EXE build complete. Hardware operation is NOT certified by this build.'
   } finally {Pop-Location}
 } elseif ($Action -eq 'UPLOAD_GITHUB') {
   $Git=CmdPath 'git.exe'
   $Remote='https://github.com/smini131-maker/RC-BOAT.git'
   $Branch='beta/ros-v2.0.0-beta.2'
   $RepoDir=Join-Path $env:TEMP ('RCBoat_ROS_upload_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
   New-Item -ItemType Directory -Force -Path $RepoDir | Out-Null
   Run $Git @('clone','--single-branch','--depth','1','--branch',$Branch,$Remote,$RepoDir)
   $dest=Join-Path $RepoDir 'beta\ros_v2.0.0_beta2'
   New-Item -ItemType Directory -Force -Path $dest | Out-Null
   $ExcludeDirectories=@('.venv','dist','build','.git','logs','__pycache__')
   function CopySources([string]$From,[string]$To){
     New-Item -ItemType Directory -Force -Path $To | Out-Null
     foreach($item in (Get-ChildItem -LiteralPath $From -Force)){
       if($item.PSIsContainer){
         if($item.Name -notin $ExcludeDirectories){CopySources $item.FullName (Join-Path $To $item.Name)}
       } elseif($item.Extension -notin @('.pyc','.pyo')) {
         Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $To $item.Name) -Force
       }
     }
   }
   CopySources $Root $dest
   $srcWorkflow=Join-Path $Root 'github_workflow\build-ros-v2-windows.yml'
   Check (Test-Path -LiteralPath $srcWorkflow) "Missing GitHub workflow: $srcWorkflow"
   $wfDir=Join-Path $RepoDir '.github\workflows'
   New-Item -ItemType Directory -Force -Path $wfDir | Out-Null
   Copy-Item -LiteralPath $srcWorkflow -Destination (Join-Path $wfDir 'build-ros-v2-beta2-windows.yml') -Force
   Push-Location $RepoDir
   try {
     $username=(& $Git config user.name)
     $email=(& $Git config user.email)
     Check (-not [string]::IsNullOrWhiteSpace($username)) 'Git author not configured. Run: git config --global user.name "Your Name"'
     Check (-not [string]::IsNullOrWhiteSpace($email)) 'Git email not configured. Run: git config --global user.email "you@example.com"'
     Run $Git @('add','--','beta/ros_v2.0.0_beta2','.github/workflows/build-ros-v2-beta2-windows.yml')
     & $Git diff --cached --quiet
     if($LASTEXITCODE -eq 0){Write-Host 'No changed files. GitHub already has the same content.'}
     elseif($LASTEXITCODE -eq 1){
       Run $Git @('commit','-m','fix: validate ROS v2 beta Windows build upload and ground-test guide')
       Run $Git @('push','origin',$Branch)
     }else{throw "git diff --cached returned $LASTEXITCODE"}
     Write-Host "Github branch: https://github.com/smini131-maker/RC-BOAT/tree/$Branch"
     Write-Host 'GitHub Actions will build the Windows EXE as an Actions artifact when workflow permissions allow.'
   } finally {Pop-Location}
 } else {
   $SSH=CmdPath 'ssh.exe'
   if ($Action -in @('DEPLOY_ROS','INSTALL_ROS')){
     $SCP=CmdPath 'scp.exe'
     $RemoteRoot='/home/jetson/rcboat_ros_ws'
     Run $SSH @($Destination,"mkdir -p '$RemoteRoot'")
     foreach($name in @('catkin_ws','deployment','systemd','matlab','qgis','tools')){
       $src=Join-Path $Root $name
       Check (Test-Path -LiteralPath $src) "Missing folder $src"
       # OpenSSH scp on Windows accepts backslashes in local paths; quote arguments via PowerShell array.
       Run $SCP @('-r',$src,($Destination+':'+$RemoteRoot+'/'))
     }
     # SCP on Windows can preserve CRLF and lose the Linux node executable flag.
     # Explicit python3 handles CRLF even in the normalizer itself.
     Run $SSH @($Destination,'python3 /home/jetson/rcboat_ros_ws/deployment/jetson/normalize_line_endings.py')
     Write-Host 'Uploaded and normalized isolated ROS workspace. Legacy v1.6.0 unchanged.'
   }
   if($Action -eq 'INSTALL_ROS'){
     Write-Host 'Preflight first. Ubuntu 20.04 ROS Noetic must be available on the Jetson.'
     Run $SSH @('-tt',$Destination,'bash /home/jetson/rcboat_ros_ws/deployment/jetson/install_jetson_ros.sh')
   }
   if($Action -eq 'CHECK_BACKEND') {Run $SSH @('-tt',$Destination,'sudo bash /home/jetson/rcboat_ros_ws/deployment/jetson/check_backend.sh --repair')}
   if($Action -eq 'CHECK_ROS') {Run $SSH @($Destination,'bash /home/jetson/rcboat_ros_ws/deployment/jetson/check_ros.sh')}
   if($Action -eq 'USE_ROS') {Run $SSH @('-tt',$Destination,'sudo bash /home/jetson/rcboat_ros_ws/deployment/jetson/backend_ctl.sh ros')}
   if($Action -eq 'USE_DAEMON') {Run $SSH @('-tt',$Destination,'sudo bash /home/jetson/rcboat_ros_ws/deployment/jetson/backend_ctl.sh daemon')}
 }
 Write-Host '[SUCCESS] Task completed.'
 exit 0
} catch {
 Write-Host ('[FAILED] '+$_.Exception.Message) -ForegroundColor Red
 Write-Host "See log: $LogFile" -ForegroundColor Yellow
 exit 1
} finally {
 if($transcript){try{Stop-Transcript | Out-Null}catch{}}
}
