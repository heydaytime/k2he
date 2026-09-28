"""USB raw HID connection to the keyboard.

The device is opened per batch of commands and closed right after, so
VIA/Keychron Launcher can still use the same interface, and unplugging or
sleeping the keyboard never leaves a stale handle behind.
"""

import time
from contextlib import contextmanager

from . import protocol

REPLY_TIMEOUT_S = 1.0


class KeyboardNotFound(Exception):
    pass


class Session:
    def __init__(self, dev):
        self._dev = dev

    def transact(self, packet):
        self._dev.write(b"\x00" + packet)  # leading byte is the HID report ID
        deadline = time.monotonic() + REPLY_TIMEOUT_S
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                raise protocol.ProtocolError("keyboard did not reply")
            reply = bytes(self._dev.read(protocol.REPORT_SIZE, remaining_ms))
            if reply and protocol.is_reply_to(packet, reply):
                return reply

    def info(self):
        reply = self.transact(protocol.signal_packet(protocol.CMD_INFO))
        protocol.check_status(reply)
        return {"protocol": reply[4], "rows": reply[5], "cols": reply[6]}

    def firmware_version(self):
        reply = self.transact(protocol.firmware_version_packet())
        return reply[1:].split(b"\x00")[0].decode(errors="replace")

    def set(self, row, col, level, pattern, ttl_s, rgb=(0, 0, 0)):
        reply = self.transact(protocol.set_packet(row, col, level, pattern, ttl_s, rgb))
        protocol.check_status(reply)

    def clear_all(self):
        protocol.check_status(self.transact(protocol.signal_packet(protocol.CMD_CLEAR_ALL)))


class Keyboard:
    def __init__(self, hid_module=None):
        self._hid = hid_module

    def _hidapi(self):
        if self._hid is None:
            import hid

            self._hid = hid
        return self._hid

    def find(self):
        for d in self._hidapi().enumerate(protocol.VENDOR_ID, 0):
            if d["usage_page"] == protocol.RAW_USAGE_PAGE and d["usage"] == protocol.RAW_USAGE:
                return d
        return None

    @contextmanager
    def open(self):
        found = self.find()
        if found is None:
            raise KeyboardNotFound("no Keychron raw HID interface found")
        dev = self._hidapi().device()
        dev.open_path(found["path"])
        try:
            yield Session(dev)
        finally:
            dev.close()
