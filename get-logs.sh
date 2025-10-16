#!/bin/bash

# fetch older logs
cat /var/log/dbus-aggregate-batteries/@* | tai64nlocal

# fetch fresh logs
tail -F -n +1 /var/log/dbus-aggregate-batteries/current | tai64nlocal
