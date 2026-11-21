# Worn: glasses app (agent B)

Android app for the MicroLumin M6 glasses (Android 9, 640×480, black = see-through).
Plain Android framework, Java, no libraries. The kit has no glasses-side SDK
(`XRAppManager`, `XRCameraManager`, `XRKeyEventManager` aren't shipped), so nothing here calls MicroLumin APIs.

## What it does

- Shows agent C's page `GET /glasses` full screen in a WebView. The page polls `/session` and draws
  the stroke animation, plays pronunciation audio, loops the ASL video and shows the result overlay.
- **Tap the temple touchpad** (or press the photo button): `worn.capturing()` → Camera2 still → `GET /session`
  for `char`/`lang` → `POST /grade` multipart `{image, char, lang}` → `worn.graded(json)`, which shows ✓ or the fix.
  The page calls `WornNative.speak(feedback)` and the app speaks it with Android TTS.
- **Double tap / swipe**: `worn.replay()` re-runs the animation and audio.
- **Long press**: shows the server URL, camera state and last key at the bottom for 5 s.
- If the server can't be reached it shows "Looking for the server…" and retries every 3 s.

Keys come from the M6 Android SDK guide §12.8: tap = `ENTER`, double tap = `F12`, long press = `F10`,
swipe = `DPAD_LEFT/RIGHT`, photo = `CAMERA` (139). Every key press is logged under `WornKeys`.
If the real hardware sends something else, change `actionFor()` in `MainActivity.java`.

## Setup (one time, on the laptop)

- JDK 17+ and the Android SDK (Android Studio installs both), plus `adb`.
- Gradle wrapper: open this folder in Android Studio once, or run `gradle wrapper --gradle-version 8.11.1`.
- On the glasses: MLDemo › Glasses › Developer › Developer Mode on, then replug USB. `adb devices -l` should list `model:XNM_Glass`.
- For Wi-Fi mode, join the glasses to the venue Wi-Fi (MLDemo › Wi-Fi).

## Run

    scripts/run.sh          # backend = laptop's en0 IP over Wi-Fi
    scripts/run.sh usb      # backend over the USB cable via adb reverse (most reliable at the table)
    scripts/run.sh 10.0.0.7 # explicit backend IP

The app remembers the last backend. To switch without reinstalling:
`adb shell am start -n com.worn.glasses/.MainActivity --es api http://<ip>:8000`.

Test without touching the glasses: `adb shell input keyevent 66` (tap = grade), `adb shell input keyevent 142` (replay).
Logs: `adb logcat -s Worn WornKeys WornCam WornWeb`. Graded photos land in `backend/captures/`. Look there if the photo is rotated or dark.

## TODO / unverified on hardware

- TODO: does the photo button (`CAMERA`) reach our app, or does the launcher keep it for the built-in camera? Tap works either way.
- TODO: can a third-party app open the camera with Camera2 while the launcher runs? If not, check whether `MLLauncher` holds it.
- TODO: camera orientation. We set `JPEG_ORIENTATION` from `SENSOR_ORIENTATION`, and the backend applies EXIF.
- TODO: check that the system WebView handles hanzi-writer and CJK/Devanagari/Arabic fonts.
