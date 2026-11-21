# ios/ (owner: agent D): Worn phone app

SwiftUI, iOS 17+. Pure HTTP to the laptop backend. It does **not** use the MicroLumin iOS SDK: the glasses app (B) talks to the backend over wifi itself, so the phone never needs Bluetooth. No SDK files live in this folder.

## Run it
1. Install Xcode (16 or newer; the project uses synced folders, objectVersion 77).
2. Open `ios/Worn.xcodeproj`. Under Target Worn › Signing & Capabilities, pick your Team. If it's taken, change the bundle id from `com.worn.phone`.
3. Plug in the iPhone and press Run. First launch: accept **Local Network**, then enter the laptop IP (`ipconfig getifaddr en0` on the laptop; the `:8000` is added automatically).
4. Phone and laptop must both be on the `event` wifi.

## What it does
- Pick a language (chips) and Write or Sign mode, then tap a phrase. That POSTs `/session` with `char_index 0` and the glasses show it.
- The lesson screen mirrors the glasses: the phrase as a strip of chars (current one highlighted, graded ones green or orange), the big char, romanization, and meaning. 🔊 plays the pronunciation on the phone.
- The phone polls `/session/result` every 0.7 s and shows the score plus feedback with a haptic. On a correct answer it auto-advances after 1.8 s: next char, then next phrase, then a lesson summary with scores.
- **Handoff:** it also polls `GET /session`. If anything else changes the session (`web/phone.html`, another phone), the app opens that lesson. Relaunching the app resumes the current session.
- Results only count if their `ts` is newer than the last one consumed and their `char`/`lang` match. So 谢谢's second 谢 never reuses the first grade.
- Controls: Prev / Replay (re-POSTs, so the glasses replay and the result clears) / Next, "Show ASL sign" toggle, and **Grade with phone**, which takes a phone photo and POSTs `/grade`. That's the demo fallback if the glasses camera fails.
- Settings (tap the status dot): server address, grader-model status, auto-advance toggle.

## Tested
- Typechecks against the macOS SDK (`swiftc -typecheck`). iOS-only bits are behind `#if os(iOS)`.
- A headless harness drove `AppModel` + `API` against a private backend on :8765: connect, start, grade, auto-advance, stale-result filter, external handoff, ASL next, lesson end, offline. 12/12 passed.
- **Not yet built for iOS on this Mac** (no Xcode here). The camera picker, AVAudioSession, and keyboard modifiers are untested.

## TODO
- TODO(D): optional MLVisionM6SDK connection status (battery, connected), only if time allows. Fork the pattern from `04_Demo_Apps/MLDemo/GlassesSession.swift`; never paste SDK code here.
