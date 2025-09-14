#!/bin/bash

# remove comment for easier troubleshooting
#set -x

echo



# stop dbus-serialbattery service
echo "Stopping dbus-aggregate-batteries..."
svc -d "/service/dbus-aggregate-batteries"


# kill driver, if still running
pkill -f "python .*/dbus-aggregate-batteries/dbus-aggregate-batteries.py"



# start dbus-serialbattery service
echo "Starting dbus-aggregate-batteries..."
svc -u "/service/dbus-aggregate-batteries"

echo
