#!/bin/bash

# Felicity BMS Service Installation Script

set -e

SERVICE_NAME="felicity-bms"
SERVICE_FILE="$SERVICE_NAME.service"
SYSTEM_SERVICE_DIR="/etc/systemd/system"

echo "Installing Felicity BMS systemd service..."

# Check if running as root for system service installation
if [[ $EUID -ne 0 ]]; then
   echo "This script needs to be run with sudo for system service installation"
   echo "Usage: sudo ./install-service.sh"
   exit 1
fi

# Copy service file to systemd directory
echo "Copying service file to $SYSTEM_SERVICE_DIR..."
cp "$SERVICE_FILE" "$SYSTEM_SERVICE_DIR/"

# Check if environment variables exist in ~/.zshenv
ZSHENV_FILE="/home/alex/.zshenv"
echo "Checking environment variables in $ZSHENV_FILE..."

if [[ -f "$ZSHENV_FILE" ]]; then
    echo "Found existing ~/.zshenv file"
    if grep -q "MQTT_HOST\|MQTT_USER\|MQTT_PASSWORD" "$ZSHENV_FILE"; then
        echo "MQTT environment variables already configured in ~/.zshenv"
    else
        echo "Adding Felicity BMS environment variables to ~/.zshenv..."
        cat >> "$ZSHENV_FILE" << EOF

# Felicity BMS Environment Variables - 2 Batteries (Series connected via RS485)
export NUM_BATTERIES=2
export MQTT_HOST=homeassistant.fritz.box
export MQTT_USER=mqtt_user
export MQTT_PASSWORD=your_mqtt_password

# Shared RS485 connection
export BMS_DEVICE=/dev/ttyUSB0
export BMS_BAUDRATE=9600

# Battery 1 Configuration (Modbus ID 1)
export BMS_CLIENT_ID_1=1

# Battery 2 Configuration (Modbus ID 2)
export BMS_CLIENT_ID_2=2
EOF
        chown alex:alex "$ZSHENV_FILE"
        echo "Environment variables added to ~/.zshenv"
    fi
else
    echo "Creating ~/.zshenv with Felicity BMS environment variables..."
    cat > "$ZSHENV_FILE" << EOF
# Felicity BMS Environment Variables - 2 Batteries (Series connected via RS485)
export NUM_BATTERIES=2
export MQTT_HOST=homeassistant.fritz.box
export MQTT_USER=mqtt_user
export MQTT_PASSWORD=your_mqtt_password

# Shared RS485 connection
export BMS_DEVICE=/dev/ttyUSB0
export BMS_BAUDRATE=9600

# Battery 1 Configuration (Modbus ID 1)
export BMS_CLIENT_ID_1=1

# Battery 2 Configuration (Modbus ID 2)
export BMS_CLIENT_ID_2=2
EOF
    chown alex:alex "$ZSHENV_FILE"
    echo "Created ~/.zshenv with environment variables"
fi

# Add user to dialout group for serial port access
echo "Adding user 'alex' to 'dialout' group for serial port access..."
usermod -a -G dialout alex

# Create udev rule for USB serial device
UDEV_RULE_FILE="/etc/udev/rules.d/99-felicity-bms.rules"
echo "Creating udev rule at $UDEV_RULE_FILE..."

cat > "$UDEV_RULE_FILE" << EOF
# Felicity BMS USB Serial Device Rule
# Allow members of dialout group to access USB serial devices
KERNEL=="ttyUSB*", GROUP="dialout", MODE="0664"
EOF

# Reload udev rules
echo "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo ""
echo "Service installed successfully!"
echo ""
echo "Next steps:"
echo "1. Edit environment variables: nano ~/.zshenv"
echo "   (Update MQTT_HOST, MQTT_USER, MQTT_PASSWORD with your values)"
echo "2. Log out and back in (or reboot) to apply group membership"
echo "3. Enable the service: sudo systemctl enable $SERVICE_NAME"
echo "4. Start the service: sudo systemctl start $SERVICE_NAME"
echo "5. Check status: sudo systemctl status $SERVICE_NAME"
echo "6. View logs: sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "MQTT Topics (2 Batteries):"
echo "  Battery 1:"
echo "    - Individual values: felicity/battery1/bms/battery_voltage, felicity/battery1/bms/state_of_charge, etc."
echo "    - Complete data: felicity/battery1/bms/all"
echo "  Battery 2:"
echo "    - Individual values: felicity/battery2/bms/battery_voltage, felicity/battery2/bms/state_of_charge, etc."
echo "    - Complete data: felicity/battery2/bms/all"
echo ""
echo "Environment variables are loaded from ~/.zshenv"
echo "Both batteries share /dev/ttyUSB0 but use different Modbus client IDs"