#!/bin/bash


# remove install script from rc.local
sed -i "/bash \/data\/dbus-aggregate-batteries\/reinstall-local.sh/d" /data/rc.local

# remove symlink to service
rm -f /service/dbus-aggregate-batteries

# kill service
pkill -f ".*dbus-aggregate-batteries.*"
