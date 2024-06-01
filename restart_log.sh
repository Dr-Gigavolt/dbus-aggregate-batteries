#!/bin/bash
kill $(pgrep -f 'multilog s25000 n4 /var/log/dbus-aggregate-batteries')
