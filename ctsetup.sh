#!/usr/bin/env bash

set -ex

SERIAL=$1

# Stop chromium
adb -s $SERIAL shell supervisorctl stop chromium

# Forward our web server to its internal port
adb -s $SERIAL reverse tcp:5192 tcp:5192

# Remount root as read write to allow modifications
adb -s $SERIAL shell mount -o remount,rw /

# Remove the old webapp (if you really want stock back, reflash the firmware in burn mode)
adb -s $SERIAL shell rm -rf /usr/share/qt-superbird-app/webapp/ || true
adb -s $SERIAL shell mkdir -p /usr/share/qt-superbird-app/webapp/

# Push our own webapp
adb -s $SERIAL push ctroot/* /usr/share/qt-superbird-app/webapp/

# Remount root back to read only
adb -s $SERIAL shell mount -o remount,ro /

# Start chromium again
adb -s $SERIAL shell supervisorctl start chromium