#!/usr/bin/env bash
set -uo pipefail
ROOT=/home/jetson/rcboat_ros_ws
style_red='\033[31;1m';reset='\033[0m'
svc(){ systemctl "$1" "$2" 2>/dev/null || true; }
dae=$(svc is-enabled rcboat.service);dactive=$(svc is-active rcboat.service)
rose=$(svc is-enabled rcboat_ros.service);rosactive=$(svc is-active rcboat_ros.service)
selected=UNKNOWN
if [[ $dae == enabled && $rose != enabled ]];then selected=DAEMON
elif [[ $rose == enabled && $dae != enabled ]];then selected=ROS
elif [[ $dae == enabled && $rose == enabled ]];then selected=BACKEND_CONFIG_CONFLICT
fi
if [[ $dactive == active && $rosactive == active ]];then
 printf "${style_red}BACKEND CONFLICT! BOTH ACTIVE${reset}\n";selected=BACKEND_CONFLICT
 if [[ ${1:-} == --repair ]];then
   echo 'Stopping both services immediately to release owners ...'
   sudo systemctl stop rcboat_ros.service rcboat.service
   sleep 1
   for d in /dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 /dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 /dev/i2c-1;do
      if fuser "$(readlink -f "$d")" >/dev/null 2>&1;then echo "OWNER STILL ACTIVE: $d";exit 4;fi
   done
   sudo python3 "$ROOT/deployment/jetson/set_safe_pwm.py" || exit 2
   sudo systemctl start rcboat.service || exit 3
   selected=DAEMON_RECOVERED
   dactive=$(svc is-active rcboat.service)
   rosactive=$(svc is-active rcboat_ros.service)
   dae=$(svc is-enabled rcboat.service)
   rose=$(svc is-enabled rcboat_ros.service)
 else
   echo 'Run sudo bash check_backend.sh --repair for safe recovery';exit 2
 fi
fi
activebackend=NONE
if [[ $dactive == active && $rosactive != active ]];then activebackend=DAEMON
elif [[ $rosactive == active && $dactive != active ]];then activebackend=ROS
elif [[ $dactive == active && $rosactive == active ]];then activebackend=CONFLICT;fi
echo "Selected boot backend: $selected"
echo "Active backend: $activebackend"
echo "rcboat.service enabled=$dae active=$dactive"
echo "rcboat_ros.service enabled=$rose active=$rosactive"
for x in GPS:/dev/serial/by-id/usb-u-blox_AG_-_www.u-blox.com_u-blox_GNSS_receiver-if00 Arduino:/dev/serial/by-id/usb-Arduino__www.arduino.cc__Arduino_Uno_55639303534351D01210-if00 I2C/PCA:/dev/i2c-1; do
 label=${x%%:*}; dev=${x#*:}
 echo -n "$label owner: "
 if command -v fuser >/dev/null;then fuser "$(readlink -f "$dev")" 2>&1 || echo '(none)'
 else echo 'fuser unavailable';fi
done
