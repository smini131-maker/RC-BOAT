# Local-only integration test. SSH/SCP are replaced with functions; no remote IO.
$ErrorActionPreference='Stop'
$ProjectRoot=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$global:DeployFixture=Join-Path $env:TEMP ('RCBoatDeployFixture_'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $global:DeployFixture -Force | Out-Null
function global:ssh.exe {
  $global:LASTEXITCODE=0
}
function global:scp.exe {
  $items=@($args)
  foreach($item in $items[1..($items.Count-2)]) {
    Copy-Item -LiteralPath $item -Destination $global:DeployFixture -Recurse
  }
  $global:LASTEXITCODE=0
}
& (Join-Path $ProjectRoot 'tools/windows/runner.ps1') -Action DEPLOY_ROS -Root $ProjectRoot -Destination 'jetson@fixture.invalid'
if(-not (Test-Path -LiteralPath (Join-Path $global:DeployFixture 'deployment_manifest.json'))){throw 'Manifest not copied'}
$unexpected=@(Get-ChildItem -LiteralPath $global:DeployFixture -Recurse -File | Where-Object { $_.Extension -eq '.pyc' })
if($unexpected.Count){throw 'Bytecode was copied'}
& python.exe (Join-Path $global:DeployFixture 'deployment/jetson/verify_release.py') --sources-only
if($LASTEXITCODE -ne 0){throw 'Cross-language staged hashes do not match'}
Write-Output 'LOCAL STAGING/SCP ARGUMENTS/PYTHON HASH VERIFICATION: PASS'
