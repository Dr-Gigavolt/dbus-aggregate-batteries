#!/bin/bash

# Current
kill $(pgrep -f 'python3 /data/apps/dbus-aggregate-batteries/aggregatebatteries.py')
# Legacy
kill $(pgrep -f 'python3 /data/dbus-aggregate-batteries/aggregatebatteries.py')
