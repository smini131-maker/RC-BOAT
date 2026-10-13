@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RCBoat_ROS_Tool.ps1" -Action Deploy %*
pause
