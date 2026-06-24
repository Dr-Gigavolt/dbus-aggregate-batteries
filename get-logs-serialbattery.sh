#!/bin/bash

# usage: /data/apps/dbus-aggregate-batteries/get-logs-serial-battery.sh [USB port number]

# fetch older logs
cat /var/log/dbus-serialbattery.ttyUSB$1/@* | tai64nlocal

# fetch fresh logs
tail -F -n +1 /var/log/dbus-serialbattery.ttyUSB$1/current | tai64nlocal
