[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Install", "Deploy", "UseRos", "UseDaemon", "UseHil", "Check", "Uninstall")]
    [string]$Action,
    [string]$HostName = "nano.local",
    [string]$User = "jetson",
    [int]$Port = 22
)

$ErrorActionPreference = "Stop"
$Remote = "${User}@${HostName}"
$BetaRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RemoteRoot = "/home/jetson/rcboat_ros_ws"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Run-Native([scriptblock]$Command, [string]$Description) {
    Write-Host "`n[$Description]" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Require-Command "ssh"
Require-Command "scp"

try {
    Run-Native { ssh -o ConnectTimeout=7 -p $Port $Remote "printf RCBOAT_SSH_OK" } "SSH connection check"

    switch ($Action) {
        "Install" {
            $LocalScript = Join-Path $BetaRoot "deployment\jetson\install_ros_dependencies.sh"
            Run-Native { scp -P $Port $LocalScript "${Remote}:/tmp/install_rcboat_ros_dependencies.sh" } "Upload ROS installer"
            Run-Native { ssh -t -p $Port $Remote "chmod +x /tmp/install_rcboat_ros_dependencies.sh && /tmp/install_rcboat_ros_dependencies.sh" } "Install ROS Noetic dependencies"
        }
        "Deploy" {
            Require-Command "tar"
            $Archive = Join-Path $env:TEMP ("rcboat_ros_beta_" + [Guid]::NewGuid().ToString("N") + ".tar.gz")
            try {
                Run-Native { tar -czf $Archive -C $BetaRoot . } "Create beta-only archive"
                Run-Native { scp -P $Port $Archive "${Remote}:/tmp/rcboat_ros_beta.tar.gz" } "Upload ROS beta"
                $RemoteCommand = "rm -rf /tmp/rcboat_ros_beta_deploy && mkdir -p /tmp/rcboat_ros_beta_deploy && tar -xzf /tmp/rcboat_ros_beta.tar.gz -C /tmp/rcboat_ros_beta_deploy && chmod +x /tmp/rcboat_ros_beta_deploy/deployment/jetson/*.sh && /tmp/rcboat_ros_beta_deploy/deployment/jetson/deploy_ros_beta.sh"
                Run-Native { ssh -t -p $Port $Remote $RemoteCommand } "Build and register ROS beta"
            }
            finally {
                Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
            }
        }
        "UseRos" {
            Run-Native { ssh -t -p $Port $Remote "sudo $RemoteRoot/deployment/rcboat_backend_ctl.sh ros" } "Switch daemon to ROS"
        }
        "UseDaemon" {
            Run-Native { ssh -t -p $Port $Remote "sudo $RemoteRoot/deployment/rcboat_backend_ctl.sh daemon" } "Restore daemon v1.6"
        }
        "UseHil" {
            Run-Native { ssh -t -p $Port $Remote "sudo $RemoteRoot/deployment/rcboat_backend_ctl.sh hil" } "Start ROS HIL without physical actuator"
        }
        "Check" {
            Run-Native { ssh -t -p $Port $Remote "$RemoteRoot/deployment/rcboat_backend_ctl.sh check" } "Check active backend"
        }
        "Uninstall" {
            Run-Native { ssh -t -p $Port $Remote "sudo $RemoteRoot/deployment/uninstall_ros_beta.sh" } "Remove ROS beta and restore daemon"
        }
    }
    Write-Host "`nCompleted: $Action on $Remote" -ForegroundColor Green
}
catch {
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($HostName -eq "nano.local") {
        Write-Host "If the hotspot does not resolve nano.local, retry with:" -ForegroundColor Yellow
        $Wrapper = @{
            Install="INSTALL_ROS.cmd"; Deploy="DEPLOY_ROS.cmd"; UseRos="USE_ROS.cmd";
            UseDaemon="USE_DAEMON.cmd"; UseHil="USE_ROS_HIL.cmd";
            Check="CHECK_ROS.cmd"; Uninstall="UNINSTALL_ROS_BETA.cmd"
        }[$Action]
        Write-Host ".\$Wrapper -HostName 10.x.x.x" -ForegroundColor Yellow
    }
    exit 1
}
