#!/usr/bin/env bash

set -ex

SERIAL=$1

# Forward our web server to its internal port
adb -s $SERIAL reverse tcp:5192 tcp:5192

# Wait to see if it automatically connects (init.py should kill the script here if it does)
sleep 3

# Stop chromium
adb -s $SERIAL shell supervisorctl stop chromium

# Check for bind mounts (taken from https://github.com/pajowu/superbird-custom-webapp)
adb -s $SERIAL shell 'mountpoint /usr/share/qt-superbird-app/webapp/ > /dev/null && umount /usr/share/qt-superbird-app/webapp' || true
adb -s $SERIAL shell 'rm -rf /tmp/webapp' || true

# Push our own webapp
adb -s $SERIAL push ctroot /tmp/webapp

# Bind mount the temporary directory
adb -s $SERIAL shell 'mount --bind /tmp/webapp /usr/share/qt-superbird-app/webapp'

# Start chromium again
adb -s $SERIAL shell supervisorctl start chromium