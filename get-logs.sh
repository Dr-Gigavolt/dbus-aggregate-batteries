#!/bin/bash

tail -F -n 100 /var/log/dbus-aggregate-batteries/current | tai64nlocal
