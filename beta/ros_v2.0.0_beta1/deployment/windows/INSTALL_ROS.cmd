@echo off
setlocal
set "DEST=%~1"
if "%DEST%"=="" set "DEST=jetson@10.85.226.215"
call "%~dp0DEPLOY_ROS.cmd" "%DEST%"
if errorlevel 1 exit /b 1
ssh -tt "%DEST%" "bash /home/jetson/rcboat_ros_ws/deployment/jetson/install_jetson_ros.sh"
if errorlevel 1 (
 echo INSTALL incomplete. Check ROS Noetic EOL dependencies, then rerun.
 exit /b 1
)
echo ROS catkin installation succeeded; ROS service remains DISABLED at boot.
