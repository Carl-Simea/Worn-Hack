#!/usr/bin/env bash
# Build, install and start Worn on the M6 glasses (plugged in over USB, Developer Mode on).
#   scripts/run.sh            backend = this laptop's Wi-Fi IP (glasses must be on the same Wi-Fi)
#   scripts/run.sh usb        backend over the USB cable (adb reverse); no Wi-Fi needed on the glasses
#   scripts/run.sh 10.0.0.7   backend at that IP
#   NOBUILD=1 scripts/run.sh  skip the Gradle build, reinstall the last APK
set -euo pipefail
cd "$(dirname "$0")/.."

PKG=com.worn.glasses
APK=app/build/outputs/apk/debug/app-debug.apk
MODE="${1:-wifi}"

# Toolchain from `brew install openjdk@17` + `brew install --cask android-commandlinetools` (sdkmanager
# "platforms;android-34" "build-tools;34.0.0" into ~/Library/Android/sdk).
[ -n "${JAVA_HOME:-}" ] || { [ -d /opt/homebrew/opt/openjdk@17 ] && export JAVA_HOME=/opt/homebrew/opt/openjdk@17; }
[ -n "${ANDROID_HOME:-}" ] || export ANDROID_HOME="$HOME/Library/Android/sdk"
[ -f local.properties ] || echo "sdk.dir=$ANDROID_HOME" > local.properties

command -v adb >/dev/null ||{ echo "adb not found (brew install android-platform-tools)"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "no glasses on adb: turn on Developer Mode in MLDemo, replug USB, run adb devices -l"; exit 1; }

case "$MODE" in
  usb)  adb reverse tcp:8000 tcp:8000; API="http://127.0.0.1:8000" ;;
  wifi) IP="$(ipconfig getifaddr en0 || true)"; [ -n "$IP" ] || { echo "no IP on en0; pass one: scripts/run.sh <ip>"; exit 1; }
        API="http://$IP:8000" ;;
  *)    API="http://$MODE:8000" ;;
esac

if [ -z "${NOBUILD:-}" ]; then ./gradlew -q :app:assembleDebug; fi
adb shell svc power stayon usb || true   # keep the display on while plugged in
adb install -r -g "$APK"      # -g grants the camera permission (no dialog to tap on the glasses)
# Fallback while the USB cable is in: the app tries $API first and drops to adb reverse only if it can't reach it.
adb reverse tcp:8000 tcp:8000 >/dev/null || true
adb reverse tcp:8790 tcp:8790 >/dev/null || true   # live camera relay (tools/camera_relay.py)
adb shell am start -n "$PKG/.MainActivity" --es api "$API" --es fallback "http://127.0.0.1:8000"
echo "started $PKG with backend $API"
echo "logs: adb logcat -s Worn WornKeys WornCam WornWeb"
