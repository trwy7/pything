#!/usr/bin/env bash

set -ex

SERIAL=$1

adb -s $SERIAL shell 'mountpoint /usr/share/qt-superbird-app/webapp/ > /dev/null && umount /usr/share/qt-superbird-app/webapp' || true

if [ "$2" != "false" ]; then
    adb -s "$SERIAL" shell supervisorctl restart chromium
fi
