param(
    [string]$JetsonIp = "10.69.235.215",
    [string]$UserName = "jetson",
    [string]$Ref = "release/1.6.0"
)

$ErrorActionPreference = "Stop"
$ExpectedVersion = "1.6.0"
$Repo = "smini131-maker/RC-BOAT"
$ArchiveUrl = "https://github.com/$Repo/archive/refs/heads/$Ref.zip"
$TempRoot = Join-Path $env:TEMP ("RCBoatDeploy_" + [guid]::NewGuid().ToString("N"))
$ZipPath = Join-Path $TempRoot "source.zip"
$ExtractPath = Join-Path $TempRoot "src"
$RemoteDir = "/home/$UserName/deploy_v$($ExpectedVersion.Replace('.','_'))_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

function Require-Command([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "Required command not found: $Name" }
    return $cmd
}

function Invoke-Ssh([string]$Command, [switch]$Tty) {
    if ($Tty) {
        & ssh -t "$UserName@$JetsonIp" $Command
    } else {
        & ssh "$UserName@$JetsonIp" $Command
    }
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed: $Command"
    }
}

Write-Host "=========================================================="
Write-Host " RC Boat v$ExpectedVersion Jetson Deployment"
Write-Host "=========================================================="
Write-Host "Target: $UserName@$JetsonIp"
Write-Host "Source ref: $Ref"
Write-Host ""
Write-Host "Close RCBoatControl first."
Write-Host "REMOVE THE PROPELLER or disconnect propulsion power."
Write-Host ""

Require-Command "ssh.exe" | Out-Null
Require-Command "scp.exe" | Out-Null
New-Item -ItemType Directory -Path $ExtractPath -Force | Out-Null

try {
    Write-Host ">>> 1/8 Download source into short TEMP path"
    $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --fail --retry 2 --connect-timeout 15 -o $ZipPath $ArchiveUrl
        if ($LASTEXITCODE -ne 0) { throw "curl download failed" }
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $ArchiveUrl -OutFile $ZipPath
    }
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        throw "Downloaded ZIP was not created."
    }

    Write-Host ">>> 2/8 Extract without PowerShell Expand-Archive"
    $tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
    if ($tar) {
        & $tar.Source -xf $ZipPath -C $ExtractPath
        if ($LASTEXITCODE -ne 0) { throw "tar.exe extraction failed" }
    } else {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $ExtractPath)
    }

    $Project = Get-ChildItem -LiteralPath $ExtractPath -Directory |
        Where-Object {
            (Test-Path -LiteralPath (Join-Path $_.FullName "VERSION")) -and
            (Test-Path -LiteralPath (Join-Path $_.FullName "jetson_patch\install_patch.sh"))
        } |
        Select-Object -First 1

    if (-not $Project) {
        throw "Extracted repository does not contain VERSION and jetson_patch."
    }

    $Version = (Get-Content -LiteralPath (Join-Path $Project.FullName "VERSION") -Raw).Trim()
    if ($Version -ne $ExpectedVersion) {
        throw "Version mismatch. Expected $ExpectedVersion but source is $Version."
    }
    Write-Host "SOURCE_VERSION_OK: $Version"

    $Patch = Join-Path $Project.FullName "jetson_patch"
    foreach ($relative in @(
        "install_patch.sh",
        "rcboat\config.py",
        "rcboat\controller.py",
        "rcboat\navigation.py",
        "rcboat\gps_runtime.py",
        "rcboat\gps_health.py"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $Patch $relative))) {
            throw "Required patch file missing: $relative"
        }
    }

    Write-Host ">>> 3/8 Capture protected Jetson file hashes"
    $CoreHashCommand = @'
set -e
sha256sum \
  /home/jetson/rcboat/routes.json \
  /home/jetson/rcboat/boat_config.json \
  /home/jetson/rcboat/rcboat/hardware.py \
  /home/jetson/rcboat/rcboat/pca_direct.py
'@
    $BeforeCore = (& ssh "$UserName@$JetsonIp" $CoreHashCommand) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) { throw "Could not read protected file hashes." }

    $NtripHashCommand = @'
if [ -f /home/jetson/rcboat/.ntrip.env ]; then
  sha256sum /home/jetson/rcboat/.ntrip.env
else
  echo MISSING
fi
'@
    $BeforeNtrip = (& ssh "$UserName@$JetsonIp" $NtripHashCommand) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect .ntrip.env." }

    Write-Host ">>> 4/8 Create remote staging"
    Invoke-Ssh "mkdir -p '$RemoteDir'"

    Write-Host ">>> 5/8 Upload selective Jetson patch"
    $RemoteScp = "$UserName@$JetsonIp" + ":" + "$RemoteDir/"
    & scp -r $Patch $RemoteScp
    if ($LASTEXITCODE -ne 0) { throw "SCP patch upload failed." }

    Write-Host ">>> 6/8 Install patch"
    Invoke-Ssh "cd '$RemoteDir/jetson_patch' && chmod +x install_patch.sh && ./install_patch.sh" -Tty

    Write-Host ">>> 7/8 Verify protected files remained unchanged"
    $AfterCore = (& ssh "$UserName@$JetsonIp" $CoreHashCommand) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) { throw "Could not read post-install hashes." }
    if ($BeforeCore -ne $AfterCore) {
        Write-Host "BEFORE:"
        Write-Host $BeforeCore
        Write-Host "AFTER:"
        Write-Host $AfterCore
        throw "Protected routes/config/hardware files changed."
    }

    $AfterNtrip = (& ssh "$UserName@$JetsonIp" $NtripHashCommand) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) { throw "Could not re-check .ntrip.env." }
    if ($BeforeNtrip -ne "MISSING" -and $BeforeNtrip -ne $AfterNtrip) {
        throw "Existing .ntrip.env changed unexpectedly."
    }
    Write-Host "PRESERVED_FILES_SHA256_OK"

    Write-Host ">>> 8/8 Verify service, semantic version, AUTO_SAFE and GPS telemetry"
    $Verify = @'
set -e
PROJECT=/home/jetson/rcboat
systemctl is-active --quiet rcboat.service
"$PROJECT/.venv/bin/python" -m py_compile "$PROJECT"/rcboat/*.py
grep -q 'SOFTWARE_VERSION = "1.6.0"' "$PROJECT/rcboat/config.py"
grep -q 'recording_samples' "$PROJECT/rcboat/navigation.py"
grep -q 'heading_deg' "$PROJECT/rcboat/navigation.py"
"$PROJECT/.venv/bin/python" - <<'PY'
import json
import socket
import time

def get_state():
    s = socket.create_connection(("127.0.0.1", 8765), timeout=3)
    s.settimeout(3)
    s.sendall((json.dumps({"command":"GET_STATE","request_id":"v160verify"})+"\n").encode())
    buf = b""
    deadline = time.time() + 4
    try:
        while time.time() < deadline:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if not raw:
                    continue
                obj = json.loads(raw.decode("utf-8"))
                if obj.get("type") == "telemetry":
                    return obj
    finally:
        s.close()
    raise RuntimeError("NO_TELEMETRY")

state = None
for _ in range(5):
    state = get_state()
    time.sleep(1)

gps = state.get("gps") or {}
pca = state.get("pca") or {}
print("software_version =", state.get("software_version"))
print("mode =", state.get("mode"))
print("operation_state =", state.get("operation_state"))
print("steering_pwm =", pca.get("steering_pwm"))
print("throttle_pwm =", pca.get("throttle_pwm"))
print("fix =", gps.get("fix_label"))
print("rtk_state =", gps.get("rtk_state"))
print("hAcc =", gps.get("hacc_m"))
print("NAV-PVT count =", gps.get("nav_pvt_message_count"))
print("UBX count =", gps.get("ubx_message_count"))
print("NMEA count =", gps.get("nmea_sentence_count"))

if state.get("software_version") != "1.6.0":
    raise SystemExit("VERSION_CHECK_FAILED")
if state.get("mode") != "AUTO":
    raise SystemExit("AUTO_MODE_CHECK_FAILED")
if state.get("operation_state") != "AUTO_SAFE":
    raise SystemExit("AUTO_SAFE_STATE_CHECK_FAILED")
if pca.get("steering_pwm") != 6000 or pca.get("throttle_pwm") != 6450:
    raise SystemExit("AUTO_SAFE_PWM_CHECK_FAILED")

print("VERSION_1.6.0_OK")
print("AUTO_SAFE_6000_6450_OK")
if int(gps.get("nav_pvt_message_count") or 0) > 0 and gps.get("hacc_m") is not None:
    print("HACC_NAV_PVT_OK")
else:
    print("HACC_NAV_PVT_PENDING")
PY
'@
    Invoke-Ssh $Verify

    Write-Host ""
    Write-Host "DEPLOY_OK v$ExpectedVersion"
    Write-Host "Remote staging: $RemoteDir"
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
