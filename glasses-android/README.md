# Worn on the glasses (agent D)

Voice-first Android app for the MicroLumin M6 (Android 9, 640×480, black = see-through, mic, speaker, camera).
Plain Android, Java, no libraries; the kit has no glasses-side SDK, so nothing here calls MicroLumin APIs.
The tutor's voice is **Scribi**; the app is **Worn**.

## How it works

- **Screens** are our own page, `app/src/main/assets/ui/index.html`, loaded with the backend as its base URL
  (same-origin calls, B's `/static/web/worn-ink.js`, `worn-confetti.js`, `worn-sfx.js`). Home, Learn
  (language › word › lesson), Write my name, Help me write, Daily 5, Journal, How to use. Every screen shows a
  breadcrumb and a green “Say …” hint, so the wearer always knows what to say next.
- **Lesson**: Watch (character, meaning, romanization, audio, stroke animation) → Your turn (stroke N of M; next
  stroke on new ink, on “next”, or after ~4 s × speed) → Check (glasses photo → `POST /grade`) → Result (score +
  one fix, or confetti) → next character / word. Never stuck: every phase has a timer.
- **Mic** (`VoiceListener`): always on, 16 kHz; an energy detector cuts utterances (noise floor = 25th percentile of
  the last 2 s, end = 600 ms below 22 % of the speaker's own peak, ≤ 7 s) and drops quiet ones (other people
  talking; threshold `loud`, default 1800). Each utterance → `POST /voice {audio, screen}` (A; Whisper on the Mac,
  ~0.5 s round trip). Muted while Scribi speaks (watchdog unmutes after 15 s).
- **Speaker**: Scribi's lines via `GET /say?text=` (the glasses have no TTS engine), pronunciation clips from
  content; one at a time.
- **Ink** (`InkWatcher`): 64×64 luma thumbnails from the camera preview (~3/s), on-device diff (paper = 70th
  percentile, ink < 0.62 × paper, new ink must persist for 2 frames, head turns reset). ≈1–2 ms per frame.
- **State**: `POST /app-state` on every change `{screen, breadcrumb (ids), breadcrumb_names, hint, phase, mic,
  listening, lang, item_id, char_index, stroke, stroke_count, last_heard}`; `/live` (B) shows it.
- **Backend**: Wi-Fi URL first, `http://127.0.0.1:8000` (adb reverse) when the Wi-Fi one doesn't answer; checked
  every 5 s, with a `connected:true` heartbeat so `GET /health` shows `glasses.connected`.
- **Button (backup)**: press = next / open the highlighted item, hold = check (I'm done), double tap = back.

## Run

    scripts/run.sh usb          # backend over the USB cable (adb reverse); most reliable at the table
    scripts/run.sh 10.0.221.236 # backend over Wi-Fi (USB stays as fallback while plugged in)
    NOBUILD=1 scripts/run.sh usb

Needs JDK 17 + Android SDK (`brew install openjdk@17`, `brew install --cask android-commandlinetools`, then
`sdkmanager "platforms;android-34" "build-tools;34.0.0"`); `run.sh` finds them. Install uses `-g` so the mic and
camera permissions need no taps on the glasses.

## Test without speaking

    adb shell am start -n com.worn.glasses/.MainActivity --es say "'learn greek'"   # any phrase, through /voice
    adb shell am start -n com.worn.glasses/.MainActivity --es key tap               # tap|double|long|left|right
    adb shell am start -n com.worn.glasses/.MainActivity --es js "worn.test\(1\)"   # force a pass (0 = fail)
    adb shell am start -n com.worn.glasses/.MainActivity --ei loud 2500              # mic loudness gate
    adb logcat -s Worn WornVoice WornWeb WornKeys
    adb exec-out screencap -p > screen.png

## Known limits

- CityTech-WiFi isolates clients (glasses can't reach the Mac over it), so the demo runs over USB.
- The open mic also hears people nearby; A's `/voice` drops chatter (unknown, no nav) and the app never speaks a
  reply to an unrecognised utterance.
- Ink detection depends on light and on looking at the page; voice and the timer always move the lesson on.
