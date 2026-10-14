from __future__ import annotations

import math
import time


class DirectLinuxPCA9685:
    """Minimal PCA9685 driver using Linux I2C directly (no Blinka/GPIO)."""

    MODE1 = 0x00
    MODE2 = 0x01
    PRESCALE = 0xFE
    LED0_ON_L = 0x06

    def __init__(self, bus_number: int = 1, address: int = 0x40, frequency_hz: int = 60) -> None:
        from smbus2 import SMBus

        self.bus = SMBus(bus_number)
        self.address = address
        self.closed = False
        self.bus.write_byte_data(address, self.MODE1, 0x00)
        self.bus.write_byte_data(address, self.MODE2, 0x04)
        self.set_frequency(frequency_hz)

    def set_frequency(self, frequency_hz: int) -> None:
        if not 24 <= frequency_hz <= 1526:
            raise ValueError("PCA9685 frequency out of range")
        prescale = int(round(25_000_000.0 / (4096.0 * frequency_hz)) - 1)
        old_mode = self.bus.read_byte_data(self.address, self.MODE1)
        self.bus.write_byte_data(self.address, self.MODE1, (old_mode & 0x7F) | 0x10)
        self.bus.write_byte_data(self.address, self.PRESCALE, prescale)
        self.bus.write_byte_data(self.address, self.MODE1, old_mode)
        time.sleep(0.005)
        self.bus.write_byte_data(self.address, self.MODE1, old_mode | 0xA1)

    def set_duty_cycle(self, channel: int, duty_16bit: int) -> None:
        if self.closed:
            raise RuntimeError("PCA9685 is closed")
        if not 0 <= channel <= 15:
            raise ValueError("PCA9685 channel out of range")
        if not 0 <= duty_16bit <= 65535:
            raise ValueError("PCA9685 duty out of range")
        off = min(4095, max(0, int(round(duty_16bit * 4095 / 65535))))
        register = self.LED0_ON_L + 4 * channel
        self.bus.write_i2c_block_data(self.address, register, [0, 0, off & 0xFF, off >> 8])

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.bus.close()

