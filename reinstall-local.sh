#!/bin/bash

# fix owner and group
chown -R root:root /data/apps/dbus-aggregate-batteries

# make files executable
chmod +x /data/apps/dbus-aggregate-batteries/*.py
chmod +x /data/apps/dbus-aggregate-batteries/*.sh
chmod +x /data/apps/dbus-aggregate-batteries/service/run
chmod +x /data/apps/dbus-aggregate-batteries/service/log/run

# create symlink to service
if [ -L "/service/dbus-aggregate-batteries" ]; then
	rm /service/dbus-aggregate-batteries
fi
ln -s /data/apps/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries

# remove old rc.local entry
sed -i "/ln -s \/data\/apps\/dbus-aggregate-batteries\/service \/service\/dbus-aggregate-batteries/d" /data/rc.local

# add entry to rc.local, if it does not exist
grep -qxF "bash /data/apps/dbus-aggregate-batteries/reinstall-local.sh" /data/rc.local || echo "bash /data/apps/dbus-aggregate-batteries/reinstall-local.sh" >> /data/rc.local

echo ""
echo "Installation successful! Please modify the settings.py file in /data/apps/dbus-aggregate-batteries to your needs and then reboot the device."
echo ""
