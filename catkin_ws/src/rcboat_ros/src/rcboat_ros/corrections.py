"""Correction transport diagnostics, independent of RTK position solution status."""
import math


def crc24q(data):
    crc = 0
    for value in data:
        crc ^= value << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


class Rtcm3Stream:
    """Extract complete CRC-checked RTCM3 frames across arbitrary TCP reads."""
    def __init__(self):
        self.buffer = bytearray()
        self.frames = 0
        self.crc_errors = 0

    def feed(self, data):
        self.buffer.extend(data)
        result = []
        while self.buffer:
            start = self.buffer.find(b'\xd3')
            if start < 0:
                self.buffer.clear()
                break
            del self.buffer[:start]
            if len(self.buffer) < 3:
                break
            if self.buffer[1] & 0xFC:
                del self.buffer[0]
                continue
            length = ((self.buffer[1] & 3) << 8) | self.buffer[2]
            if length < 2:  # A message needs at least the 12-bit RTCM message ID.
                del self.buffer[0]
                continue
            size = length + 6
            if len(self.buffer) < size:
                break
            frame = bytes(self.buffer[:size])
            if crc24q(frame[:-3]) != int.from_bytes(frame[-3:], 'big'):
                self.crc_errors += 1
                del self.buffer[0]
                continue
            del self.buffer[:size]
            self.frames += 1
            result.append(frame)
        return result


def reception_status(last_frame, now):
    if last_frame is None:
        return None, 'no_data'
    age = now - last_frame
    if not math.isfinite(age) or age < 0:
        return None, 'invalid'
    return round(age, 3), 'valid' if age <= 5.0 else 'stale'


class HttpChunkedStream:
    """Remove HTTP chunk framing before scanning binary RTCM frames."""
    def __init__(self):
        self.buffer = bytearray()
        self.size = None
        self.done = False

    def feed(self, data):
        self.buffer.extend(data)
        output = bytearray()
        while not self.done:
            if self.size is None:
                end = self.buffer.find(b'\r\n')
                if end < 0:
                    if len(self.buffer) > 8192:
                        raise ValueError('invalid chunk header')
                    break
                self.size = int(self.buffer[:end].split(b';', 1)[0], 16)
                del self.buffer[:end + 2]
                if self.size == 0:
                    self.done = True
                    break
                if not 0 < self.size <= 2_000_000:
                    raise ValueError('invalid chunk length')
            if len(self.buffer) < self.size + 2:
                break
            if self.buffer[self.size:self.size + 2] != b'\r\n':
                raise ValueError('invalid chunk terminator')
            output.extend(self.buffer[:self.size])
            del self.buffer[:self.size + 2]
            self.size = None
        return bytes(output)


def refresh_transport_status(status, now):
    """Recompute on the Jetson even if the NTRIP publisher has stopped."""
    result = dict(status)
    if result.get('correction_age_source') != 'JETSON_RTCM3_CRC_RECEPTION':
        result.update(correction_age=None, last_correction_age_s=None,
                      correction_age_status='unsupported')
        return result
    age, validity = reception_status(result.get('last_rtcm_monotonic'), now)
    result.update(correction_age=age, last_correction_age_s=age,
                  correction_age_status=validity)
    return result


def refresh_receiver_status(gps, now):
    result = dict(gps)
    if result.get('receiver_correction_age_s') is not None:
        stamp = result.get('receiver_correction_age_monotonic')
        if stamp is None or now < stamp:
            result['receiver_correction_age_status'] = 'invalid'
        elif now - stamp > 2:
            result['receiver_correction_age_status'] = 'stale'
    return result
