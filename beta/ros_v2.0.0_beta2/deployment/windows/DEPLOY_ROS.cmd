@echo off
setlocal
set "DEST=%~1"
if "%DEST%"=="" set "DEST=jetson@10.85.226.215"
set "SRC=%~dp0..\.."
echo Uploading separate ROS project to %DEST% without changing stable v1.6.0
ssh "%DEST%" "mkdir -p /home/jetson/rcboat_ros_ws" || exit /b 1
scp -r "%SRC%/catkin_ws" "%SRC%/deployment" "%SRC%/systemd" "%SRC%/matlab" "%SRC%/tools" "%DEST%:/home/jetson/rcboat_ros_ws/" || exit /b 1
echo Copied. See README_KO.md for dependency installation and catkin build.
