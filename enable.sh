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



# add empty config.ini, if it does not exist to make it easier for users to add custom settings
filename="/data/apps/dbus-aggregate-batteries/config.ini"
if [ ! -f "$filename" ]; then
    {
        echo "[DEFAULT]"
        echo
        echo "; If you want to add custom values/settings, then check the values/settings you want to change in \"config.default.ini\""
        echo "; and insert them below to persist future driver updates."
        echo "; NOTICE: Do not copy the whole file, but only the values/settings you want to change."
        echo
        echo "; Example (remove the semicolon \";\" to uncomment and activate the value/setting):"
        echo "; NR_OF_BATTERIES = 2"
        echo "; NR_OF_CELLS_PER_BATTERY = 16"
        echo
        echo
    } > $filename
fi



# stop dbus-aggregate-batteries service
if [ -d "/service/dbus-aggregate-batteries" ]; then
    echo "Stop dbus-aggregate-batteries service..."
    svc -d "/service/dbus-aggregate-batteries"
fi

sleep 1

# kill driver, if still running
pkill -f "supervise dbus-aggregate-batteries"
pkill -f "multilog .* /var/log/dbus-aggregate-batteries"
pkill -f "python3 .*/dbus-aggregate-batteries/dbus-aggregate-batteries.py"
# backwards compatibility for older versions
pkill -f "python3 .*/dbus-aggregate-batteries/.*.py"


# create symlink to service
if [ -L "/service/dbus-aggregate-batteries" ]; then
	rm /service/dbus-aggregate-batteries
fi
ln -s /data/apps/dbus-aggregate-batteries/service /service/dbus-aggregate-batteries


echo
echo "#################################"
echo "# First activation instructions #"
echo "#################################"
echo
echo "CUSTOM SETTINGS: If you want to add custom settings, then check the settings you want to change in \"/data/apps/dbus-aggregate-batteries/config.default.ini\""
echo "                 and add them to \"/data/apps/dbus-aggregate-batteries/config.ini\" to persist future driver updates."
echo
echo
line=$(cat /data/apps/dbus-aggregate-batteries/dbus-aggregate-batteries.py | grep "VERSION =" | awk -F'"' '{print "v" $2}')
echo "*** dbus-aggregate-batteries $line was installed. ***"
echo
echo
