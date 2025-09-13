#!/bin/bash

# check if file exists
# >= v2.0.0
if [ -f /data/apps/dbus-serialbattery/restart.sh ]; then
    bash /data/apps/dbus-serialbattery/restart.sh
# < v2.0.0
elif [ -f /data/etc/dbus-serialbattery/restart-driver.sh ]; then
    bash /data/etc/dbus-serialbattery/restart-driver.sh
else
    echo "The dbus-serialbattery restart script was not found."
    exit 1
fi
