param(
  [Parameter(Mandatory=$true)]
  [ValidateSet('CHECK_WINDOWS','BUILD_GUI','CHECK_BACKEND','CHECK_ROS','DEPLOY_ROS','INSTALL_ROS')]
  [string]$Action,
  [Parameter(Mandatory=$true)][string]$Root,
  [string]$Destination='jetson@10.180.227.215'
)
$ErrorActionPreference='Stop'
$Root=(Resolve-Path -LiteralPath $Root).Path
function Need([string]$Name) {
  if(-not (Get-Command $Name -ErrorAction SilentlyContinue)){throw "$Name is required"}
}
function Remote([string]$Command) {
  Need 'ssh.exe'
  & ssh.exe $Destination $Command
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
  foreach($Name in @('catkin_ws','deployment','systemd','matlab')) {
    & scp.exe -r (Join-Path $Root $Name) ($Destination + ':/home/jetson/rcboat_ros_ws/')
    if($LASTEXITCODE -ne 0){throw "SCP failed: $Name"}
  }
  Remote 'python3 /home/jetson/rcboat_ros_ws/deployment/jetson/normalize_line_endings.py'
  if($Action -eq 'DEPLOY_ROS'){Write-Host 'ROS source deployed. Build it inside the Jetson SSH session.';exit 0}
  Remote 'cd /home/jetson/rcboat_ros_ws && bash deployment/jetson/install_jetson_ros.sh'
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
