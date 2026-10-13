@echo off
setlocal
call "%~dp0..\BUILD_ROS_GUI.cmd" %*
exit /b %ERRORLEVEL%
