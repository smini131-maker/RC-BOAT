"""DirectLinuxPCA9685: single-owner Linux I2C output driver."""
import time
class DirectLinuxPCA9685:
    def __init__(self, bus=1, address=0x40, frequency=60):
        from smbus2 import SMBus
        self.bus = SMBus(bus); self.address=address; self.closed=False
        try:
            self.bus.write_byte_data(address, 0x00, 0)
            self.bus.write_byte_data(address, 0x01, 4)
            prescale=int(round(25_000_000.0 / (4096.0 * frequency))-1)
            old=self.bus.read_byte_data(address,0)
            self.bus.write_byte_data(address,0,(old&0x7f)|0x10)
            self.bus.write_byte_data(address,0xfe,prescale)
            self.bus.write_byte_data(address,0,old)
            time.sleep(.005)
            self.bus.write_byte_data(address,0,old|0xa1)
        except Exception:
            self.close()
            raise
    def set_duty_cycle(self,channel,duty16):
        if self.closed: raise RuntimeError('PCA closed')
        if not 0<=channel<=15 or not 0<=duty16<=65535: raise ValueError('unsafe PCA argument')
        off=min(4095,max(0,int(round(duty16*4095/65535))))
        self.bus.write_i2c_block_data(self.address,0x06+4*channel,[0,0,off&255,off>>8])
    def close(self):
        if not self.closed: self.closed=True; self.bus.close()
