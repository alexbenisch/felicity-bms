#!/usr/bin/env python3
"""
Felicity BMS raw register diagnostic.

Pulls every register the running felicity-bms service already talks to
(firmware version block, the 10-register 0x1302 block, and the 20-register
0x132A cell/temp block) for every configured battery, decodes the fields
main.py already knows about, and prints the ones it currently discards as
both raw hex and signed/unsigned int16 so they can be correlated against
whatever the BMS is actually doing (e.g. a blinking/not-charging pack).

Run this with the felicity-bms systemd service STOPPED - it is not safe to
share the RS485 bus with another poller mid-transaction.

Usage: uv run diagnose.py [--json report.json]
"""
import argparse
import json
import os
import time
from datetime import datetime, timezone

import serial
from dotenv import load_dotenv

load_dotenv()

DEVICE = os.getenv("BMS_DEVICE", "/dev/ttyUSB0")
BAUDRATE = int(os.getenv("BMS_BAUDRATE", "9600"))
NUM_BATTERIES = int(os.getenv("NUM_BATTERIES", "1"))


def modbus_crc(msg: bytes) -> int:
    crc = 0xFFFF
    for b in msg:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc


def send_command(clientid_hex: str, reg_hex: str, count_hex: str) -> bytes:
    no_crc_command = bytes.fromhex(f"{clientid_hex} 03 {reg_hex} {count_hex}")
    crc = modbus_crc(no_crc_command)
    full_command = no_crc_command + crc.to_bytes(2, byteorder="little")

    with serial.serial_for_url(DEVICE, BAUDRATE) as s:
        s.timeout = 1
        s.write_timeout = 1
        s.flushInput()
        s.flushOutput()
        s.write(full_command)
        time.sleep(0.1)

        resp_header = s.read(3)
        if len(resp_header) < 3:
            raise RuntimeError(f"incomplete response header: {resp_header.hex()}")

        data_length = resp_header[2]
        resp_data = s.read(data_length)
        if len(resp_data) < data_length:
            raise RuntimeError(
                f"incomplete response data: got {len(resp_data)}, expected {data_length}"
            )
        return resp_data


def regs(data: bytes) -> list[dict]:
    """Split a response into 16-bit registers, decoded both ways."""
    out = []
    for i in range(0, len(data) - 1, 2):
        raw = data[i : i + 2]
        u16 = int.from_bytes(raw, byteorder="big")
        s16 = u16 - 0x10000 if u16 & 0x8000 else u16
        out.append({"offset": i, "hex": raw.hex(), "uint16": u16, "int16": s16})
    return out


def diagnose_battery(battery_id: int) -> dict:
    clientid = int(os.getenv(f"BMS_CLIENT_ID_{battery_id}", str(battery_id)))
    clientid_hex = "%0.2x" % clientid
    report: dict = {"battery_id": battery_id, "modbus_client_id": clientid}

    # --- BMS firmware version: register 0xF80B, 1 register ---
    try:
        data = send_command(clientid_hex, "F8 0B", "00 01")
        version = int.from_bytes(data[0:2], byteorder="big")
        report["bms_version"] = {"raw_hex": data.hex(), "value": version}
    except Exception as e:
        report["bms_version"] = {"error": str(e)}

    # --- Main block: register 0x1302, 10 registers (20 bytes) ---
    # main.py only decodes offsets 8-9 (voltage), 10-11 (current), 18-19 (soc).
    # Offsets 0-7 and 12-17 are read off the wire today and discarded.
    try:
        data = send_command(clientid_hex, "13 02", "00 0A")
        all_regs = regs(data)

        battery_voltage = round(int.from_bytes(data[8:10], byteorder="big") * 0.01, 2)
        signed_current = int.from_bytes(data[10:12], byteorder="big")
        signed_current -= (signed_current & 0x8000) << 1
        battery_current = round(signed_current * 0.1, 2)
        soc = int.from_bytes(data[18:20], byteorder="big")

        known_offsets = {8: "battery_voltage", 10: "battery_current", 18: "state_of_charge"}
        for reg in all_regs:
            reg["known_as"] = known_offsets.get(reg["offset"])

        report["main_block_0x1302"] = {
            "raw_hex": data.hex(),
            "registers": all_regs,
            "decoded": {
                "battery_voltage_v": battery_voltage,
                "battery_current_a": battery_current,
                "state_of_charge_pct": soc,
            },
        }
    except Exception as e:
        report["main_block_0x1302"] = {"error": str(e)}

    # --- Cell/temp block: register 0x132A, 20 registers (16 cells + 4 temps) ---
    try:
        data = send_command(clientid_hex, "13 2A", "00 14")
        cell_voltages = []
        for i in range(16):
            v = round(int.from_bytes(data[i * 2 : i * 2 + 2], byteorder="big") * 0.001, 4)
            cell_voltages.append(v)
        temps = []
        for i in range(4):
            off = (16 + i) * 2
            temps.append(int.from_bytes(data[off : off + 2], byteorder="big"))

        vmax, vmin = max(cell_voltages), min(cell_voltages)
        report["cell_block_0x132A"] = {
            "raw_hex": data.hex(),
            "cell_voltages_v": cell_voltages,
            "temp_sensors_c": temps,
            "cell_voltage_max": vmax,
            "cell_voltage_min": vmin,
            "cell_voltage_delta_mv": round((vmax - vmin) * 1000, 1),
        }
    except Exception as e:
        report["cell_block_0x132A"] = {"error": str(e)}

    return report


def render_text(reports: list[dict]) -> str:
    lines = []
    lines.append(f"Felicity BMS diagnostic — {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Device: {DEVICE} @ {BAUDRATE} baud")
    lines.append("")

    for r in reports:
        bid = r["battery_id"]
        lines.append(f"===== Battery {bid} (Modbus client 0x{r['modbus_client_id']:02x}) =====")

        v = r.get("bms_version", {})
        if "error" in v:
            lines.append(f"  BMS version: ERROR - {v['error']}")
        else:
            lines.append(f"  BMS version: {v['value']} (raw {v['raw_hex']})")

        mb = r.get("main_block_0x1302", {})
        if "error" in mb:
            lines.append(f"  Main block 0x1302: ERROR - {mb['error']}")
        else:
            d = mb["decoded"]
            lines.append(
                f"  Voltage: {d['battery_voltage_v']} V   "
                f"Current: {d['battery_current_a']} A   "
                f"SoC: {d['state_of_charge_pct']} %"
            )
            lines.append("  All 10 registers in this block (offset: hex / uint16 / int16 / known-as):")
            for reg in mb["registers"]:
                known = reg["known_as"] or "unidentified"
                lines.append(
                    f"    [{reg['offset']:2d}] {reg['hex']}  u16={reg['uint16']:6d}  "
                    f"s16={reg['int16']:6d}  ({known})"
                )

        cb = r.get("cell_block_0x132A", {})
        if "error" in cb:
            lines.append(f"  Cell/temp block 0x132A: ERROR - {cb['error']}")
        else:
            lines.append(f"  Cell voltages (V): {cb['cell_voltages_v']}")
            lines.append(
                f"  Cell max/min/delta: {cb['cell_voltage_max']} / "
                f"{cb['cell_voltage_min']} / {cb['cell_voltage_delta_mv']} mV"
            )
            lines.append(f"  Temp sensors (raw units, scale unconfirmed): {cb['temp_sensors_c']}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="also write full raw report as JSON to this path")
    args = parser.parse_args()

    reports = [diagnose_battery(i) for i in range(1, NUM_BATTERIES + 1)]

    text = render_text(reports)
    print(text)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(reports, f, indent=2)
        print(f"\nFull raw report written to {args.json}")


if __name__ == "__main__":
    main()
