#!/bin/bash

# remove comment for easier troubleshooting
#set -x



# fix permissions
chmod +x /data/apps/dbus-aggregate-batteries/*.sh
chmod +x /data/apps/dbus-aggregate-batteries/*.py
chmod +x /data/apps/dbus-aggregate-batteries/service/run
chmod +x /data/apps/dbus-aggregate-batteries/service/log/run



# add install-script to rc.local to be ready for firmware update
filename=/data/rc.local
if [ ! -f "$filename" ]; then
    echo "#!/bin/bash" > "$filename"
    chmod 755 "$filename"
fi



### needed for upgrading from older versions | start ###
# remove old install script from rc.local
sed -i "/.*dbus-aggregate-batteries.*/d" /data/rc.local
### needed for upgrading from older versions | end ###



# add enable script to rc.local
# log the output to a file and run it in the background to prevent blocking the boot process
grep -qxF "bash /data/apps/dbus-aggregate-batteries/enable.sh > /data/apps/dbus-aggregate-batteries/startup.log 2>&1 &" $filename || echo "bash /data/apps/dbus-aggregate-batteries/enable.sh > /data/apps/dbus-aggregate-batteries/startup.log 2>&1 &" >> $filename



# stop dbus-aggregate-batteries service
echo "Stop dbus-aggregate-batteries service..."
svc -d "/service/dbus-aggregate-batteries"

sleep 1

# kill driver, if still running
pkill -f "supervise dbus-aggregate-batteries"
pkill -f "multilog .* /var/log/dbus-aggregate-batteries"
pkill -f "python .*/dbus-aggregate-batteries/dbus-aggregate-batteries.py"



echo
echo "#################################"
echo "# First activation instructions #"
echo "#################################"
echo
echo "CUSTOM SETTINGS: If you want to add custom settings, then check the settings you want to change in \"/data/apps/dbus-aggregate-batteries/config.default.ini\""
echo "                 and add them to \"/data/apps/dbus-aggregate-batteries/config.ini\" to persist future driver updates."
echo
echo
line=$(cat /data/apps/dbus-aggregate-batteries/utils.py | grep VERSION | awk -F'"' '{print "v" $2}')
echo "*** dbus-aggregate-batteries $line was installed. ***"
echo
echo
