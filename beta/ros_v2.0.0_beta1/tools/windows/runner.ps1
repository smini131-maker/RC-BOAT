param(
 [ValidateSet('BUILD_GUI','UPLOAD_GITHUB','CHECK_BACKEND','CHECK_ROS','DEPLOY_ROS','INSTALL_ROS','USE_ROS','USE_DAEMON')]
 [string]$Action,
 [string]$Root,
 [string]$Destination = 'jetson@10.85.226.215'
)
$ErrorActionPreference = 'Stop'
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
try {
 Start-Transcript -LiteralPath $LogFile -Force -ErrorAction Stop | Out-Null
 $transcript=$true
 Write-Host "RCBoat ROS v2.0.0-beta.1 | $Action"
 Write-Host "Full log: $LogFile"
 if ($Action -eq 'BUILD_GUI') {
   $PythonExe = $null
   $c = Get-Command py.exe -ErrorAction SilentlyContinue
   if ($c) {
     foreach($ver in @('3.11','3.12')){
       & $c.Source "-$ver" -c 'import sys; assert sys.maxsize > 2**32; print(sys.version)' 2>$null
       if($LASTEXITCODE -eq 0){$PythonExe=$c.Source;$PythonPre=@("-$ver");break}
     }
   }
   if(-not $PythonExe){
     $c=Get-Command python.exe -ErrorAction SilentlyContinue
     if($c){
       & $c.Source -c 'import sys; assert (3,11) <= sys.version_info[:2] <= (3,12) and sys.maxsize>2**32' 2>$null
       if($LASTEXITCODE -eq 0){$PythonExe=$c.Source;$PythonPre=@()}
     }
   }
   Check ($null -ne $PythonExe) 'Python 3.11 or 3.12 x64 not found. Install from python.org with the launcher (py.exe) and PATH enabled.'
   $AppDir = Join-Path $Root 'windows_gui'
   $Venv = Join-Path $AppDir '.venv'
   $Exe = Join-Path $Venv 'Scripts\python.exe'
   Push-Location $AppDir
   try {
     if(-not (Test-Path -LiteralPath $Exe)){
       Run $PythonExe ($PythonPre + @('-m','venv',$Venv))
     }
     Run $Exe @('-m','pip','--version')
     Run $Exe @('-m','pip','install','-r',(Join-Path $AppDir 'requirements.txt'))
     # Import verifies dependencies before the potentially long packaging step.
     Run $Exe @('-c','import PySide6,paramiko,PyInstaller;print("Python GUI dependencies OK")')
     Run $Exe @('-m','unittest','discover','-s',(Join-Path $Root 'tests'),'-v')
     Run $Exe @('app.py','--smoke-test')
     $Name = 'RCBoatControl_ROS_v2.0.0-beta.1'
     Run $Exe @('-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name',$Name,'app.py')
     $Artifact=Join-Path $AppDir ('dist\'+$Name+'.exe')
     Check (Test-Path -LiteralPath $Artifact) "Build command returned success but EXE is missing: $Artifact"
     Check ((Get-Item -LiteralPath $Artifact).Length -gt 100000) 'EXE size unexpectedly small'
     Write-Host "BUILT FILE: $Artifact"
     Write-Host "SHA256: $((Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash)"
     Write-Host 'Windows GUI EXE build complete. Hardware operation is NOT certified by this build.'
   } finally {Pop-Location}
 } elseif ($Action -eq 'UPLOAD_GITHUB') {
   $Git=CmdPath 'git.exe'
   $Remote='https://github.com/smini131-maker/RC-BOAT.git'
   $Branch='beta/ros-v2.0.0-beta.1'
   $RepoDir=Join-Path $env:TEMP ('RCBoat_ROS_upload_'+(Get-Date -Format 'yyyyMMdd_HHmmss'))
   New-Item -ItemType Directory -Force -Path $RepoDir | Out-Null
   Run $Git @('clone','--single-branch','--depth','1','--branch',$Branch,$Remote,$RepoDir)
   $dest=Join-Path $RepoDir 'beta\ros_v2.0.0_beta1'
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
   Copy-Item -LiteralPath $srcWorkflow -Destination (Join-Path $wfDir 'build-ros-v2-windows.yml') -Force
   Push-Location $RepoDir
   try {
     $username=(& $Git config user.name)
     $email=(& $Git config user.email)
     Check (-not [string]::IsNullOrWhiteSpace($username)) 'Git author not configured. Run: git config --global user.name "Your Name"'
     Check (-not [string]::IsNullOrWhiteSpace($email)) 'Git email not configured. Run: git config --global user.email "you@example.com"'
     Run $Git @('add','--','beta/ros_v2.0.0_beta1','.github/workflows/build-ros-v2-windows.yml')
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
     foreach($name in @('catkin_ws','deployment','systemd','matlab','tools')){
       $src=Join-Path $Root $name
       Check (Test-Path -LiteralPath $src) "Missing folder $src"
       # OpenSSH scp on Windows accepts backslashes in local paths; quote arguments via PowerShell array.
       Run $SCP @('-r',$src,($Destination+':'+$RemoteRoot+'/'))
     }
     Write-Host 'Uploaded ROS workspace only. Legacy v1.6.0 directory is unchanged.'
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
