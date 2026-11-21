#!/usr/bin/env bash
# One command: build Worn, install it on the plugged-in M6 glasses, make it the glasses' home app, launch it.
#   ./install.sh               backend over the USB cable (adb reverse) — the demo setup
#   ./install.sh 10.0.221.236  backend over Wi-Fi at that IP (USB stays as the fallback while plugged in)
#   NOBUILD=1 ./install.sh     reinstall the last build
#   NOHOME=1 ./install.sh      don't make Worn the home app
# Undo demo mode: adb shell cmd package set-home-activity com.mlaixr.launcher/.MainActivity
#   (or on the glasses: hold Back for 3 s).
set -euo pipefail
cd "$(dirname "$0")"

PKG=com.worn.glasses
ACT="$PKG/.MainActivity"
APK=app/build/outputs/apk/debug/app-debug.apk
[ -n "${JAVA_HOME:-}" ] || { [ -d /opt/homebrew/opt/openjdk@17 ] && export JAVA_HOME=/opt/homebrew/opt/openjdk@17; }
[ -n "${ANDROID_HOME:-}" ] || export ANDROID_HOME="$HOME/Library/Android/sdk"
[ -f local.properties ] || echo "sdk.dir=$ANDROID_HOME" > local.properties

adb get-state >/dev/null 2>&1 || { echo "No glasses on adb. Plug them in (Developer Mode on in MLDemo), then: adb devices -l"; exit 1; }

if [ -n "${1:-}" ]; then API="http://$1:8000"; else API="http://127.0.0.1:8000"; fi

[ -n "${NOBUILD:-}" ] || ./gradlew -q :app:assembleDebug
echo "› installing"
adb install -r -g "$APK" >/dev/null
if [ -z "${NOHOME:-}" ]; then
  adb shell cmd package set-home-activity "$ACT" >/dev/null && echo "› Worn is the glasses' home app"
fi
adb shell svc power stayon usb || true                 # display stays on while plugged in
adb reverse tcp:8000 tcp:8000 >/dev/null               # backend over USB
adb reverse tcp:8790 tcp:8790 >/dev/null               # live camera relay over USB
if ! lsof -ti tcp:8790 >/dev/null 2>&1; then           # start the camera relay if it isn't running
  nohup python3 tools/camera_relay.py >/tmp/worn-camera-relay.log 2>&1 &
  echo "› camera relay started on :8790 (log /tmp/worn-camera-relay.log, view http://localhost:8790/view)"
fi
adb shell am start -n "$ACT" --es api "$API" --es fallback "http://127.0.0.1:8000" >/dev/null
echo "› Worn started (backend $API). Logs: adb logcat -s Worn WornVoice WornWeb WornStream"
