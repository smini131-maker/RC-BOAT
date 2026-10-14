param(
    [string]$HostName = "10.122.105.215",
    [string]$UserName = "jetson"
)
$ErrorActionPreference = "Stop"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$RemoteDir = "/home/${UserName}/rcboat_deploy_${Stamp}"
ssh "${UserName}@${HostName}" "mkdir -p '$RemoteDir'"
scp -r .\jetson_backend .\jetson_patch "${UserName}@${HostName}:$RemoteDir/"
Write-Host "업로드 완료: $RemoteDir"
Write-Host "Jetson에서 $RemoteDir/jetson_patch/install_patch.sh 를 실행하세요."
