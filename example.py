import asyncio
import serial
import time
import crcmod
import argparse
from terminaltables import AsciiTable  # type: ignore
from collections import namedtuple

InverterItem = namedtuple("InverterItem", ["name", "desc", "value", "unit"])

class FelicityBMSManager:
    """ FelicityBMSManager"""
    def __init__(self, command: str, clientid : int = 1, device: str = "/dev/ttyUSB0", baudrate: int = 9600):
    #def __init__(self, command: str, value: int = None, device: str = "socket://192.168.0.205:4196", baudrate: int = 9600, inverterport: str = "/dev/ttyRS232", inverterbaud: int = 2400):
        
        clientid_hex = "%0.2x" % int(clientid)

        #print(command, clientid, clientid_hex, device, baudrate)
        
        self.command: str = command
        self.clientid_hex = clientid_hex
        self.device: str = device
        self.baudrate: int = baudrate

    async def get_data_async(self) -> dict[str, InverterItem]:

        data: dict[str, InverterItem] = {}

        #data["test"] = InverterItem(
        #            name="t1",
        #            desc="desc1",
        #            value="value1",
        #            unit="unit1")

        device = ""
        baud = 0
        no_crc_command = None
        command_result = None

        if self.command == "GetBMSVersion":
            device = self.device
            baud = self.baudrate
            no_crc_command = bytes.fromhex(self.clientid_hex + " 03 F8 0B 00 01") # Battery version
            command_result = self.send_command(device, baud, no_crc_command);
        elif self.command == "GetBMSCellInformation":
            device = self.device
            baud = self.baudrate
            no_crc_command = bytes.fromhex(self.clientid_hex + " 03 13 2A 00 14") # Cell voltage and temperature
            command_result = self.send_command(device, baud, no_crc_command);
        elif self.command == "GetBMSBatteryInformation":
            device = self.device
            baud = self.baudrate
            no_crc_command = bytes.fromhex(self.clientid_hex + " 03 13 02 00 0A") # Battery information
            command_result = self.send_command(device, baud, no_crc_command);
        else:
            print("Invalid command")

        if command_result is not None:

            if self.command == "GetBMSCellInformation":

                #datacount = int(len(command_result) / 2)
                #print(datacount)


                #for i in range(datacount):

                #    cell_key = str(i + 1)
                #    value = command_result[i * 2:i * 2 + 2]

                #    print(value, value.hex());

                #    data["Cell" + cell_key + " Voltage"] = InverterItem(
                #        name="Cell" + cell_key + " Voltage",
                #        desc="Cell" + cell_key + " Voltage",
                #        value=round(int.from_bytes(value, byteorder='big') * 1, 4),
                #        unit="V")

                cellcount = 16

                for i in range (0, cellcount):

                    cell_key = str(i + 1)
                    value = command_result[i * 2:i * 2 + 2]
                    #print(i, value.hex())

                    data["Cell" + cell_key + " Voltage"] = InverterItem(
                        name="Cell" + cell_key + " Voltage",
                        desc="Cell" + cell_key + " Voltage",
                        value=round(int.from_bytes(value, byteorder='big') * 0.001, 4),
                        unit="V")

                for i in range (0, 4):

                    cell_key = str(i + 1)
                    value = command_result[(cellcount + i) * 2:(cellcount + i) * 2 + 2]

                    #value = value * 0.001

                    data["Sensor" + cell_key + " Temperature"] = InverterItem(
                        name="Sensor" + cell_key + " Temperature",
                        desc="Sensor" + cell_key + " Temperature",
                        value=round(int.from_bytes(value, byteorder='big') * 1, 4),
                        unit="°C")

            elif self.command == "GetBMSVersion":
                version = command_result[0:2]
                #print(type(version), version.hex(), int.from_bytes(version, byteorder='big'))

                data["BMSVersion"] = InverterItem(
                    name="BMSVersion",
                    desc="BMSVersion",
                    value=int.from_bytes(command_result[0:2], byteorder='big'),
                    unit="")

            elif self.command == "GetBMSBatteryInformation":
                #soc = command_result[18:20]
                #print(type(soc), soc.hex(), int.from_bytes(soc, byteorder='big'))

                data["BatteryVoltage"] = InverterItem(
                    name="BatteryVoltage",
                    desc="BatteryVoltage",
                    value=round(int.from_bytes(command_result[8:10], byteorder='big') * 0.01, 4),
                    unit="V")

                signedCurrent = int.from_bytes(command_result[10:12], byteorder='big')
                #print(signedCurrent)
                signedCurrent -= (signedCurrent & 0x8000) << 1
                #print(signedCurrent)

                data["BatteryCurrent"] = InverterItem(
                    name="BatteryCurrent",
                    desc="BatteryCurrent",
                    value=round(signedCurrent * 0.1, 2),
                    unit="A")

                data["SOC"] = InverterItem(
                    name="SOC",
                    desc="Ladezustand",
                    value=int.from_bytes(command_result[18:20], byteorder='big'),
                    unit="%")

        return data

    def send_command(self, serial_port, serial_baud, no_crc_command):

        crc = self.modbusCrc(no_crc_command)
        ba = crc.to_bytes(2, byteorder='little')
        full_command = no_crc_command + ba

        #print("full command", full_command.hex())

        try:

            with serial.serial_for_url(serial_port, serial_baud) as s:

#               while True:
#                       response_line = s.read_until(b"\r")
#                       #dataline = s.readline();
#                       print(response_line)

                #print("Executing command via serialio...")
                s.timeout = 1
                s.write_timeout = 1
                s.flushInput()
                s.flushOutput()
                s.write(full_command)
                #s.write(full_command+'\r')
                time.sleep(0.1) # give serial port time to receive the data
#               response_line = s.read_until(b"\r")
#               print("serial response was: %s", response_line)

#               bytes = bytearray(response_line)
#               print(bytes.hex())

                resp = s.read(3)
                #print(resp.hex())

                datalength = resp[2]

                resp = s.read(datalength)
                #print(type(resp), resp.hex())

#               hex_val = resp.hex()
#               byte_val = bytes([int(hex_val[i : i + 2], 16) for i in range(0, len(hex_val), 2)])
#               print(byte_val)

                return resp

                #soc = resp[18:20]
                #print(type(soc), soc.hex(), int.from_bytes(soc, byteorder='big'))


#               return response_line
        except Exception as e:
            print(f"Serial read error: {e}")
            print("Command execution failed")

    def modbusCrc(self, msg:str) -> int:
        crc = 0xFFFF
        for n in range(len(msg)):
            crc ^= msg[n]
            for i in range(8):
                if crc & 1:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return crc

    def get_data(self) -> dict[str, InverterItem]:
            return asyncio.run(self.get_data_async())

def main():
    """Command line interface to the Felicity BMS"""
    parser = argparse.ArgumentParser(
        description="Retrieve data from Felicity Inverter and BMS"
    )

    parser.add_argument("command", help="Command")
    parser.add_argument("-c", "--clientid", default=1, help="ClientId (DIP Settings)")
    parser.add_argument("-d", "--device", default="/dev/ttyUSB0", help="Device (e.g. /dev/ttyUSB0 or socket://ipadress:port")
    parser.add_argument("-b", "--baudrate", default="9600", help="baudrate")

    #parser.add_argument(
    #    "--details", action="store_true", help="show more details"
    #)
    #parser.add_argument('--version', action='version', version=version)
    args: dict[str, InverterItem] = parser.parse_args()

    data: list[InverterItem] = FelicityBMSManager(args.command, args.clientid, args.device, args.baudrate).get_data()
    #if args.details:
    #    table: list[list[str]] = [["Item", "Value", "ID"]] + [
    #        [item.desc, f"{item.value} {item.unit}", id]
    #        for id, item in data.items()
    #    ]
    #else:
    table = [["Name", "Description", "Value"]] + [
        [item.name, item.desc, f"{item.value} {item.unit}"] for item in data.values()
    ]
    print(AsciiTable(table).table)

if __name__ == "__main__":
    main()
