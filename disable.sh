#!/bin/bash

# remove comment for easier troubleshooting
#set -x


echo
echo "Disabling dbus-aggregate-batteries driver..."


# remove services
rm -rf /service/dbus-aggregate-batteries


# kill driver, if still running
pkill -f "supervise dbus-aggregate-batteries"
pkill -f "multilog .* /var/log/dbus-aggregate-batteries"
pkill -f "python .*/dbus-aggregate-batteries/aggregatebatteries.py"

# remove enable script from rc.local
sed -i "\;bash /data/apps/dbus-aggregate-batteries/enable.sh > /data/apps/dbus-aggregate-batteries/startup.log 2>&1 &;d" /data/rc.local


### needed for upgrading from older versions | start ###
# remove old install script from rc.local
sed -i "/.*dbus-aggregate-batteries.*/d" /data/rc.local
### needed for upgrading from older versions | end ###

echo "The dbus-aggregate-batteries driver was disabled".
echo
