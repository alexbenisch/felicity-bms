# Felicity BMS MQTT Publisher

A Python application that reads data from Felicity Battery Management Systems (BMS) via RS485 serial communication and publishes it to MQTT. Supports multiple batteries connected in series on the same RS485 bus with different Modbus device IDs. This project is based on the Victron MPPT project structure.

## Features

- Reads comprehensive BMS data from multiple batteries via shared RS485 connection
- Supports batteries connected in series with different Modbus device IDs
- Concurrent data reading with proper RS485 bus locking
- Publishes individual values and complete datasets to MQTT per battery
- Systemd service for automatic startup and monitoring
- Configurable via environment variables in ~/.zshenv
- Robust error handling and logging

## BMS Data

The application reads and publishes the following data:

### Battery Information
- **Battery Voltage** - Total battery pack voltage (V)
- **Battery Current** - Current flow in/out of battery (A) 
- **State of Charge** - Battery charge level (%)
- **BMS Version** - Firmware version

### Cell Information  
- **Cell Voltages** - Individual cell voltages for 16 cells (V)
- **Temperature Sensors** - 4 temperature sensor readings (�C)

## Installation

1. **Clone and setup the project:**
   ```bash
   cd /home/alex/felicity
   uv sync  # Install dependencies
   ```

2. **Install as a systemd service:**
   ```bash
   sudo ./install-service.sh
   ```

3. **Configure environment variables:**
   ```bash
   sudo nano /etc/default/felicity-bms
   ```
   
   Set your MQTT broker details:
   ```bash
   MQTT_HOST=your.mqtt.broker.com
   MQTT_USER=your_username  
   MQTT_PASSWORD=your_password
   ```

4. **Enable and start the service:**
   ```bash
   sudo systemctl enable felicity-bms
   sudo systemctl start felicity-bms
   ```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NUM_BATTERIES` | No | `1` | Number of batteries (1 or 2) |
| `BMS_DEVICE` | No | `/dev/ttyUSB0` | Shared RS485 device path |
| `BMS_BAUDRATE` | No | `9600` | Serial communication speed |
| `BMS_CLIENT_ID_1` | No | `1` | Modbus client ID for Battery 1 |
| `BMS_CLIENT_ID_2` | No | `2` | Modbus client ID for Battery 2 |
| `MQTT_HOST` | Yes | - | MQTT broker hostname |
| `MQTT_USER` | Yes | - | MQTT username |
| `MQTT_PASSWORD` | Yes | - | MQTT password |

### Hardware Setup

1. Connect both batteries to computer via shared USB-to-RS485 adapter
2. Batteries are connected in series on the same RS485 bus
3. Each battery must have a unique Modbus device ID (typically 1 and 2)
4. Ensure `/dev/ttyUSB0` is available 
5. User must be in `dialout` group (handled by install script)

## MQTT Topics

Data is published to these topics every 30 seconds for each battery:

### Battery 1 Topics
```
felicity/battery1/bms/battery_voltage     # 53.45
felicity/battery1/bms/battery_current     # -12.5  
felicity/battery1/bms/state_of_charge     # 85
felicity/battery1/bms/bms_version         # 123
felicity/battery1/bms/cell_01_voltage     # 3.340
felicity/battery1/bms/cell_02_voltage     # 3.342
...
felicity/battery1/bms/temp_sensor_1       # 25
felicity/battery1/bms/temp_sensor_2       # 26
felicity/battery1/bms/all                 # JSON with all values
```

### Battery 2 Topics  
```
felicity/battery2/bms/battery_voltage     # 53.12
felicity/battery2/bms/battery_current     # -12.3
felicity/battery2/bms/state_of_charge     # 84
felicity/battery2/bms/bms_version         # 123
felicity/battery2/bms/cell_01_voltage     # 3.335
felicity/battery2/bms/cell_02_voltage     # 3.338
...
felicity/battery2/bms/temp_sensor_1       # 24
felicity/battery2/bms/temp_sensor_2       # 25
felicity/battery2/bms/all                 # JSON with all values
```

## Usage

### Manual Testing
```bash
# Test BMS communication
uv run main.py

# Test with environment variables
MQTT_HOST=broker.local MQTT_USER=test MQTT_PASSWORD=pass uv run main.py
```

### Service Management
```bash
# Check service status
sudo systemctl status felicity-bms

# View logs
sudo journalctl -u felicity-bms -f

# Restart service
sudo systemctl restart felicity-bms

# Stop service
sudo systemctl stop felicity-bms
```

## Troubleshooting

### Common Issues

1. **Serial port access denied**
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```

2. **No response from BMS**
   - Check physical connections
   - Verify `/dev/ttyUSB0` exists: `ls -la /dev/ttyUSB*`
   - Check BMS client ID setting
   - Try different baudrate

3. **MQTT connection failed**
   - Verify MQTT broker is accessible
   - Check credentials in `/etc/default/felicity-bms`
   - Test with MQTT client: `mosquitto_pub -h broker -u user -P pass -t test -m "test"`

### Debugging
Enable debug logging by editing the service:
```bash
sudo systemctl edit felicity-bms
```
Add:
```ini
[Service]
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/uv run main.py --debug
```

## Protocol Details

The application uses Modbus RTU over RS485 to communicate with the Felicity BMS:

- **Client ID**: Configurable (default: 1)
- **Baud Rate**: 9600 (configurable)
- **Data Format**: 8N1
- **Commands**:
  - `0x03 0xF8 0x0B 0x00 0x01` - Get BMS version
  - `0x03 0x13 0x02 0x00 0x0A` - Get battery information
  - `0x03 0x13 0x2A 0x00 0x14` - Get cell information

## Integration

### Home Assistant
The MQTT topics can be automatically discovered by Home Assistant with appropriate MQTT discovery messages, or manually configured:

```yaml
sensor:
  - platform: mqtt
    name: "Battery Voltage"
    state_topic: "felicity/bms/battery_voltage"
    unit_of_measurement: "V"
    device_class: "voltage"
    
  - platform: mqtt  
    name: "Battery SOC"
    state_topic: "felicity/bms/state_of_charge"
    unit_of_measurement: "%"
    device_class: "battery"
```

## Development

Based on `example.py` reference implementation. The code structure follows the Victron MPPT project template for consistency.

## License

MIT License - see LICENSE file for details.