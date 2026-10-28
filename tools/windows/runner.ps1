param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('CHECK_WINDOWS','BUILD_GUI','CHECK_BACKEND','CHECK_ROS','DEPLOY_ROS','INSTALL_ROS')]
  [string]$Action,
  [Parameter(Mandatory=$true)][string]$Root,
  [string]$Destination='jetson@10.227.56.215'
)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path -LiteralPath $Root).Path
function Need([string]$Name) {
  if(-not (Get-Command $Name -ErrorAction SilentlyContinue)){throw "$Name is required"}
}
function Remote([string]$Command,[switch]$Interactive) {
  Need 'ssh.exe'
  if($Interactive) { & ssh.exe -t $Destination $Command }
  else { & ssh.exe $Destination $Command }
  if($LASTEXITCODE -ne 0){throw "SSH command failed: $Command"}
}
if($Action -eq 'CHECK_WINDOWS') {
  Need 'python.exe'; Need 'ssh.exe'; Need 'scp.exe'
  & python.exe --version
  Write-Host 'Windows prerequisites are available.'
  exit 0
}
if($Action -eq 'BUILD_GUI') {
  & (Join-Path $Root 'windows_gui\build.bat')
  exit $LASTEXITCODE
}
if($Action -in @('DEPLOY_ROS','INSTALL_ROS')) {
  Need 'scp.exe'
  Remote 'mkdir -p /home/jetson/rcboat_ros_ws'
  $Stage=Join-Path $env:LOCALAPPDATA ('RCBoatDeploy\'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $Stage -Force | Out-Null
  $RuntimeFiles=@(Get-Item -LiteralPath (Join-Path $Root 'VERSION'))
  foreach($Name in @('catkin_ws','deployment','systemd','matlab')) {
    $RuntimeFiles+=@(Get-ChildItem -LiteralPath (Join-Path $Root $Name) -Recurse -File |
      Where-Object { $_.FullName -notmatch '[\\/](__pycache__|build|devel|logs)[\\/]' -and $_.Extension -notin @('.pyc','.pyo','.log') })
  }
  $Manifest=@{version=(Get-Content -LiteralPath (Join-Path $Root 'VERSION') -Raw).Trim();files=@{}}
  foreach($File in $RuntimeFiles) {
    $Relative=$File.FullName.Substring($Root.Length+1)
    $Target=Join-Path $Stage $Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Target
    $Bytes=[IO.File]::ReadAllBytes($Target)
    if($File.Extension -in @('.py','.sh','.service','.launch','.yaml','.xml','.msg','.srv','.json','.txt') -or $File.Name -in @('VERSION','CMakeLists.txt')) {
      $Content=[Text.Encoding]::UTF8.GetString($Bytes).Replace("`r`n","`n")
      $Bytes=[Text.Encoding]::UTF8.GetBytes($Content)
    }
    $Hasher=[Security.Cryptography.SHA256]::Create()
    try { $Hash=[BitConverter]::ToString($Hasher.ComputeHash($Bytes)).Replace('-','').ToLowerInvariant() }
    finally { $Hasher.Dispose() }
    $Manifest.files[$Relative.Replace('\','/')]=$Hash
  }
  $ManifestPath=Join-Path $Stage 'deployment_manifest.json'
  [IO.File]::WriteAllText($ManifestPath,($Manifest | ConvertTo-Json -Depth 4),(New-Object Text.UTF8Encoding($false)))
  $UploadItems=@('catkin_ws','deployment','systemd','matlab','VERSION','deployment_manifest.json') | ForEach-Object { Join-Path $Stage $_ }
  & scp.exe -r @UploadItems ($Destination + ':/home/jetson/rcboat_ros_ws/')
  if($LASTEXITCODE -ne 0){throw 'SCP failed; installation must not continue'}
  Remote 'python3 /home/jetson/rcboat_ros_ws/deployment/jetson/normalize_line_endings.py'
  Remote 'python3 /home/jetson/rcboat_ros_ws/deployment/jetson/verify_release.py --sources-only'
  if($Action -eq 'DEPLOY_ROS'){Write-Host 'Source hashes verified. NEXT: run install_jetson_ros.sh inside the Jetson SSH session. Source transfer alone does not update running processes.';exit 0}
  Remote 'cd /home/jetson/rcboat_ros_ws && bash deployment/jetson/install_jetson_ros.sh' -Interactive
  exit 0
}
if($Action -eq 'CHECK_ROS') {
  Remote 'bash /home/jetson/rcboat_ros_ws/deployment/jetson/check_ros.sh'
  exit 0
}
if($Action -eq 'CHECK_BACKEND') {
  Remote 'bash /home/jetson/rcboat_ros_ws/deployment/jetson/check_backend.sh'
  exit 0
}
