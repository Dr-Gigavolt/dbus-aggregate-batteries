#!/bin/bash

# download and install the latest version of the script
latest_release=$(curl -s https://api.github.com/repos/Dr-Gigavolt/dbus-aggregate-batteries/releases/latest | grep "tag_name" | cut -d : -f 2,3 | tr -d "\ " | tr -d \" | tr -d \, | sed 's/:$//')

echo "Downloading latest release: $latest_release"

# backup settings.py
if [ -f "/data/dbus-aggregate-batteries/settings.py" ]; then
    mv /data/dbus-aggregate-batteries/settings.py /data/dbus-aggregate-batteries_settings.py.backup
fi


cd /tmp


# download driver
wget -O dbus-aggregate-batteries_latest.zip https://github.com/Dr-Gigavolt/dbus-aggregate-batteries/archive/refs/tags/$latest_release.zip
if [ $? -ne 0 ]; then
    echo "Error during downloading the ZIP file. Please try again."
    # restore settings.py
    if [ -f "/data/dbus-aggregate-batteries_settings.py.backup" ]; then
        echo "Backup current settings.py"
        mv /data/dbus-aggregate-batteries_settings.py.backup /data/dbus-aggregate-batteries/settings.py
    fi
    # exit
fi


unzip -q /tmp/dbus-aggregate-batteries_latest.zip

# check if destination folder exists and remove it
if [ -d "/data/dbus-aggregate-batteries" ]; then
    rm -rf /data/dbus-aggregate-batteries
fi

# move extracted files to destination
mv /tmp/dbus-aggregate-batteries-$latest_release /data/dbus-aggregate-batteries


# restore settings.py
if [ -f "/data/dbus-aggregate-batteries_settings.py.backup" ]; then
    # rename settings.py
    mv /data/dbus-aggregate-batteries/settings.py /data/dbus-aggregate-batteries/settings.new-version.py
    # restore settings.py
    echo "Restore settings.py"
    mv /data/dbus-aggregate-batteries_settings.py.backup /data/dbus-aggregate-batteries/settings.py
fi


# start reinstall-local.sh
bash /data/dbus-aggregate-batteries/reinstall-local.sh
