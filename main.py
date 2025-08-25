#!/usr/bin/env python3
"""
Felicity BMS MQTT Publisher
Reads battery management system data from /dev/ttyUSB0 and publishes to MQTT
Based on the Victron MPPT project structure
"""
import asyncio
import os
import json
import serial
import time
import logging
from collections import namedtuple
from datetime import datetime
from typing import Dict, Any, Optional

from dotenv import load_dotenv
import paho.mqtt.client as mqtt

load_dotenv()

# Global lock for shared RS485 device access
RS485_LOCK = asyncio.Lock()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

InverterItem = namedtuple("InverterItem", ["name", "desc", "value", "unit"])

class FelicityBMSReader:
    """Felicity Battery Management System Reader with MQTT Publishing"""
    
    def __init__(self, battery_id: int = 1):
        # BMS Configuration
        self.battery_id = battery_id
        self.clientid = int(os.getenv(f'BMS_CLIENT_ID_{battery_id}', str(battery_id)))
        self.clientid_hex = "%0.2x" % self.clientid
        # All batteries share the same RS485 device but have different Modbus client IDs
        self.device = os.getenv(f'BMS_DEVICE_{battery_id}', os.getenv('BMS_DEVICE', '/dev/ttyUSB0'))
        self.baudrate = int(os.getenv(f'BMS_BAUDRATE_{battery_id}', os.getenv('BMS_BAUDRATE', '9600')))
        
        # MQTT Configuration  
        self.mqtt_host = os.getenv("MQTT_HOST")
        self.mqtt_user = os.getenv('MQTT_USER')
        self.mqtt_password = os.getenv('MQTT_PASSWORD')
        self.mqtt_client: Optional[mqtt.Client] = None
        
        # Validate required environment variables
        if not all([self.mqtt_user, self.mqtt_password]):
            raise ValueError("Missing required environment variables")
        
        logger.info(f"Initialized FelicityBMSReader for Battery {self.battery_id}:")
        logger.info(f"  BMS Device: {self.device}")
        logger.info(f"  BMS Baudrate: {self.baudrate}")
        logger.info(f"  BMS Client ID: {self.clientid} (0x{self.clientid_hex})")
        logger.info(f"  MQTT Host: {self.mqtt_host}")
        logger.info(f"  MQTT User: {self.mqtt_user}")
        logger.info(f"  MQTT Topic Base: felicity/battery{self.battery_id}/bms")

    def setup_mqtt(self):
        """Setup MQTT client connection"""
        self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_password)
        
        def on_connect(client, userdata, flags, rc, properties):
            if rc == 0:
                logger.info(f"Battery {self.battery_id}: Connected to MQTT broker")
            else:
                logger.error(f"Battery {self.battery_id}: Failed to connect to MQTT broker: {rc}")
        
        def on_disconnect(client, userdata, flags, rc, properties):
            logger.info(f"Battery {self.battery_id}: Disconnected from MQTT broker")
        
        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_disconnect = on_disconnect
        
        try:
            self.mqtt_client.connect(self.mqtt_host, 1883, 60)
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Error connecting to MQTT: {e}")
            raise

    def modbus_crc(self, msg: bytes) -> int:
        """Calculate Modbus CRC16"""
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

    async def send_command(self, no_crc_command: bytes) -> bytes:
        """Send command to BMS and return response"""
        crc = self.modbus_crc(no_crc_command)
        crc_bytes = crc.to_bytes(2, byteorder='little')
        full_command = no_crc_command + crc_bytes
        
        logger.debug(f"Battery {self.battery_id}: Sending command: {full_command.hex()}")
        
        # Use async lock to prevent concurrent access to shared RS485 device
        async with RS485_LOCK:
            try:
                with serial.serial_for_url(self.device, self.baudrate) as s:
                    s.timeout = 1
                    s.write_timeout = 1
                    s.flushInput()
                    s.flushOutput()
                    
                    # Send command
                    s.write(full_command)
                    time.sleep(0.1)  # Give serial port time to receive the data
                    
                    # Read response header (3 bytes)
                    resp_header = s.read(3)
                    if len(resp_header) < 3:
                        raise Exception("Incomplete response header")
                    
                    logger.debug(f"Battery {self.battery_id}: Response header: {resp_header.hex()}")
                    
                    # Get data length from header
                    data_length = resp_header[2]
                    
                    # Read data payload
                    resp_data = s.read(data_length)
                    if len(resp_data) < data_length:
                        raise Exception(f"Incomplete response data: got {len(resp_data)}, expected {data_length}")
                    
                    logger.debug(f"Battery {self.battery_id}: Response data: {resp_data.hex()}")
                    return resp_data
                    
            except Exception as e:
                logger.error(f"Battery {self.battery_id}: Serial communication error: {e}")
                raise

    async def get_bms_version(self) -> Dict[str, InverterItem]:
        """Get BMS firmware version"""
        logger.debug(f"Battery {self.battery_id}: Getting BMS version...")
        no_crc_command = bytes.fromhex(f"{self.clientid_hex} 03 F8 0B 00 01")
        
        try:
            response = await self.send_command(no_crc_command)
            version = int.from_bytes(response[0:2], byteorder='big')
            
            return {
                "bms_version": InverterItem(
                    name="bms_version",
                    desc="BMS Firmware Version",
                    value=version,
                    unit=""
                )
            }
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Failed to get BMS version: {e}")
            return {}

    async def get_battery_information(self) -> Dict[str, InverterItem]:
        """Get battery voltage, current, and SOC"""
        logger.debug(f"Battery {self.battery_id}: Getting battery information...")
        no_crc_command = bytes.fromhex(f"{self.clientid_hex} 03 13 02 00 0A")
        
        try:
            response = await self.send_command(no_crc_command)
            
            # Battery voltage (bytes 8-9)
            battery_voltage = round(int.from_bytes(response[8:10], byteorder='big') * 0.01, 2)
            
            # Battery current (bytes 10-11) - signed value
            signed_current = int.from_bytes(response[10:12], byteorder='big')
            signed_current -= (signed_current & 0x8000) << 1  # Convert to signed
            battery_current = round(signed_current * 0.1, 2)
            
            # State of charge (bytes 18-19)
            soc = int.from_bytes(response[18:20], byteorder='big')
            
            return {
                "battery_voltage": InverterItem(
                    name="battery_voltage",
                    desc="Battery Voltage",
                    value=battery_voltage,
                    unit="V"
                ),
                "battery_current": InverterItem(
                    name="battery_current",
                    desc="Battery Current",
                    value=battery_current,
                    unit="A"
                ),
                "state_of_charge": InverterItem(
                    name="state_of_charge",
                    desc="State of Charge",
                    value=soc,
                    unit="%"
                )
            }
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Failed to get battery information: {e}")
            return {}

    async def get_cell_information(self) -> Dict[str, InverterItem]:
        """Get individual cell voltages and temperatures"""
        logger.debug(f"Battery {self.battery_id}: Getting cell information...")
        no_crc_command = bytes.fromhex(f"{self.clientid_hex} 03 13 2A 00 14")
        
        try:
            response = await self.send_command(no_crc_command)
            data = {}
            
            # Cell voltages (16 cells, 2 bytes each)
            cellcount = 16
            for i in range(cellcount):
                cell_num = i + 1
                voltage_bytes = response[i * 2:i * 2 + 2]
                voltage = round(int.from_bytes(voltage_bytes, byteorder='big') * 0.001, 4)
                
                data[f"cell_{cell_num:02d}_voltage"] = InverterItem(
                    name=f"cell_{cell_num:02d}_voltage",
                    desc=f"Cell {cell_num} Voltage",
                    value=voltage,
                    unit="V"
                )
            
            # Temperature sensors (4 sensors, 2 bytes each)
            for i in range(4):
                sensor_num = i + 1
                temp_bytes = response[(cellcount + i) * 2:(cellcount + i) * 2 + 2]
                temperature = int.from_bytes(temp_bytes, byteorder='big')
                
                data[f"temp_sensor_{sensor_num}"] = InverterItem(
                    name=f"temp_sensor_{sensor_num}",
                    desc=f"Temperature Sensor {sensor_num}",
                    value=temperature,
                    unit="°C"
                )
            
            return data
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Failed to get cell information: {e}")
            return {}

    async def read_bms_data(self) -> Optional[Dict[str, Any]]:
        """Read all BMS data and return as dictionary"""
        logger.info(f"Battery {self.battery_id}: Reading BMS data from {self.device}...")
        
        try:
            all_data = {}
            
            # Get BMS version
            version_data = await self.get_bms_version()
            all_data.update(version_data)
            
            # Get battery information
            battery_data = await self.get_battery_information()
            all_data.update(battery_data)
            
            # Get cell information
            cell_data = await self.get_cell_information()
            all_data.update(cell_data)
            
            if all_data:
                logger.info(f"Battery {self.battery_id}: Successfully read BMS data")
                # Convert InverterItem namedtuples to simple values for JSON serialization
                converted_data = {}
                for key, item in all_data.items():
                    converted_data[key] = item.value
                
                return {
                    'timestamp': datetime.now().isoformat(),
                    **converted_data
                }
            return None
            
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Error reading BMS data: {e}")
            return None

    def publish_to_mqtt(self, data: Dict[str, Any]):
        """Publish BMS data to MQTT"""
        if not self.mqtt_client or not data:
            return
        
        base_topic = f"homeassistant/felicity/battery{self.battery_id}"
        
        # Publish individual values
        for key, value in data.items():
            if value is not None:
                topic = f"{base_topic}/{key}"
                payload = str(value)
                
                try:
                    result = self.mqtt_client.publish(topic, payload, retain=True)
                    if result.rc == mqtt.MQTT_ERR_SUCCESS:
                        logger.debug(f"Battery {self.battery_id}: Published {key}: {payload}")
                    else:
                        logger.warning(f"Battery {self.battery_id}: Failed to publish {key}")
                except Exception as e:
                    logger.error(f"Battery {self.battery_id}: Error publishing {key}: {e}")
        
        # Publish complete data as JSON
        full_data_topic = f"{base_topic}/all"
        full_payload = json.dumps(data)
        try:
            self.mqtt_client.publish(full_data_topic, full_payload, retain=True)
            logger.info(f"Battery {self.battery_id}: Published complete BMS data to MQTT")
        except Exception as e:
            logger.error(f"Battery {self.battery_id}: Error publishing full data: {e}")

    async def run(self):
        """Main run loop"""
        logger.info(f"Starting Felicity BMS MQTT Publisher for Battery {self.battery_id}")
        
        self.setup_mqtt()
        
        try:
            while True:
                data = await self.read_bms_data()
                if data:
                    self.publish_to_mqtt(data)
                else:
                    logger.warning(f"No data received from BMS Battery {self.battery_id}")
                
                await asyncio.sleep(30)  # Read every 30 seconds
                
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()

async def run_single_battery(battery_id: int):
    """Run BMS reader for a single battery"""
    try:
        reader = FelicityBMSReader(battery_id)
        await reader.run()
    except Exception as e:
        logger.error(f"Error with Battery {battery_id}: {e}")

async def main():
    """Main function - supports multiple batteries"""
    try:
        # Check how many batteries are configured
        num_batteries = int(os.getenv('NUM_BATTERIES', '1'))
        
        if num_batteries == 1:
            # Single battery mode
            reader = FelicityBMSReader(1)
            await reader.run()
        else:
            # Multiple battery mode - run concurrently
            logger.info(f"Starting {num_batteries} battery readers...")
            tasks = []
            for battery_id in range(1, num_batteries + 1):
                task = asyncio.create_task(run_single_battery(battery_id))
                tasks.append(task)
            
            # Wait for all tasks to complete
            await asyncio.gather(*tasks)
            
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please set the following environment variables:")
        logger.error("- NUM_BATTERIES (optional, defaults to 1)")
        logger.error("- BMS_DEVICE (or BMS_DEVICE_1, BMS_DEVICE_2, etc.)")
        logger.error("- BMS_BAUDRATE (optional, defaults to 9600)")
        logger.error("- BMS_CLIENT_ID (optional, defaults to battery number)")
        logger.error("- MQTT_HOST (required)")
        logger.error("- MQTT_USER (required)")
        logger.error("- MQTT_PASSWORD (required)")
    except Exception as e:
        logger.error(f"Application error: {e}")

if __name__ == "__main__":
    asyncio.run(main())