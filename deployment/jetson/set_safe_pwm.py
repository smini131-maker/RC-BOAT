#!/usr/bin/env python3
"""Write only with the exclusive actuator lock; verify PCA register readback."""
import sys
from pathlib import Path
p=Path(__file__).resolve().parents[2]/'catkin_ws/src/rcboat_ros/src'
sys.path.insert(0,str(p))
from rcboat_ros.direct_pca import DirectLinuxPCA9685
from rcboat_ros.common import SAFE_STEERING, SAFE_THROTTLE, PCA_OWNER_LOCK

def check(pca,ch,pwm):
    expected=min(4095,max(0,int(round(pwm*4095/65535))))
    addr=0x06+4*ch
    block=pca.bus.read_i2c_block_data(pca.address,addr,4)
    off=block[2]|((block[3]&15)<<8)
    if expected != off: raise RuntimeError(f'CH{ch} readback {off}, expected {expected}')

def main():
    import fcntl
    with open(PCA_OWNER_LOCK,'a') as owner:
        try:fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('SKIPPED: actuator already owns PCA; no second I2C writer started')
            return
        pca=DirectLinuxPCA9685()
        try:
            pca.set_duty_cycle(6,SAFE_THROTTLE)
            pca.set_duty_cycle(0,SAFE_STEERING)
            check(pca,6,SAFE_THROTTLE);check(pca,0,SAFE_STEERING)
            print('PCA REGISTERS MATCH SAFE COMMANDS 6000 / 6450 (not measured motor output)')
        finally:pca.close()

if __name__=='__main__':main()
