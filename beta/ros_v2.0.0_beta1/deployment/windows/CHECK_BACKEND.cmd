@echo off
setlocal
set "DEST=%~1"
if "%DEST%"=="" set "DEST=jetson@10.85.226.215"
ssh -tt "%DEST%" "sudo bash /home/jetson/rcboat_ros_ws/deployment/jetson/check_backend.sh --repair"
