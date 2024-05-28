#!/bin/bash

# fix owner and group
chown -R root:root /data/etc/dbus-serialbattery

# make files executable
chmod +x /data/dbus-aggregate-batteries/*.py
chmod +x /data/dbus-aggregate-batteries/*.sh
chmod +x /data/dbus-aggregate-batteries/service/run
chmod +x /data/dbus-aggregate-batteries/service/log/run

# create symlink to service, if it does not exist
if [ ! -L "/service/dbus-aggregate-batteries" ]; then
    ln -s /data/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries
fi

# remove old rc.local entry
sed -i "/ln -s \/data\/dbus-aggregate-batteries\/service \/service\/dbus-aggregate-batteries/d" /data/rc.local

# add entry to rc.local, if it does not exist
grep -qxF "bash /data/dbus-aggregate-batteries/reinstall-local.sh" /data/rc.local || echo "bash /data/dbus-aggregate-batteries/reinstall-local.sh" >> /data/rc.local

echo ""
echo "Installation successful! Please modify the settings.py file in /data/dbus-aggregate-batteries to your needs and then reboot the device."
echo ""
