#!/bin/bash

# remove comment for easier troubleshooting
#set -x

# disable driver
bash /data/apps/dbus-aggregate-batteries/disable.sh



read -r -p "Do you want to delete the install and configuration files in \"/data/apps/dbus-aggregate-batteries\" and also the logs? If unsure, just press enter. [y/N] " response
echo
response=${response,,} # tolower
if [[ $response =~ ^([yY][eE][sS]|[yY])$ ]]; then
    # remove dbus-aggregate-batteries folder
    rm -rf /data/apps/dbus-aggregate-batteries

    # remove logs
    rm -rf /var/log/dbus-aggregate-batteries

    echo "The folder \"/data/apps/dbus-aggregate-batteries\" and the logs were removed."
    echo
fi



echo "The dbus-aggregate-batteries driver was uninstalled. Please reboot."
echo
