#!/usr/bin/env python3
"""Poll register 0x1350 on both Felicity BMS packs and log timestamped values.

Run with felicity-bms.service stopped. Ctrl-C to stop; appends to the log
so it's safe to leave running under nohup/setsid.
"""
import os
import time
from datetime import datetime, timezone

import serial
from dotenv import load_dotenv

load_dotenv()

DEVICE = os.getenv("BMS_DEVICE", "/dev/ttyUSB0")
BAUDRATE = int(os.getenv("BMS_BAUDRATE", "9600"))
LOG = os.path.expanduser("~/felicity/poll_1350.log")


def modbus_crc(msg: bytes) -> int:
    crc = 0xFFFF
    for b in msg:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def read_reg(client_id: int, reg: int) -> int | None:
    cmd = bytes([client_id, 0x03, (reg >> 8) & 0xFF, reg & 0xFF, 0x00, 0x01])
    full = cmd + modbus_crc(cmd).to_bytes(2, byteorder="little")
    try:
        with serial.serial_for_url(DEVICE, BAUDRATE) as s:
            s.timeout = 1
            s.write_timeout = 1
            s.flushInput()
            s.flushOutput()
            s.write(full)
            time.sleep(0.1)
            header = s.read(3)
            if len(header) < 3:
                return None
            data = s.read(header[2])
            if len(data) < 2:
                return None
            return int.from_bytes(data[0:2], byteorder="big")
    except Exception:
        return None


def main():
    print(f"Logging to {LOG} every 10s. Ctrl-C to stop.")
    last = (None, None)
    with open(LOG, "a") as f:
        f.write(f"\n--- poll started {datetime.now(timezone.utc).isoformat()} ---\n")
        f.flush()
        while True:
            v1 = read_reg(1, 0x1350)
            v2 = read_reg(2, 0x1350)
            ts = datetime.now(timezone.utc).isoformat()
            line = f"{ts}  battery1=0x1350:{v1}  battery2=0x1350:{v2}"
            if (v1, v2) != last:
                line += "  <-- CHANGED"
                last = (v1, v2)
            f.write(line + "\n")
            f.flush()
            print(line)
            time.sleep(10)


if __name__ == "__main__":
    main()
