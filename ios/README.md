# ios/ (owner: agent D): Worn phone app

SwiftUI, iOS 17+. Pure HTTP to the laptop backend. It does **not** use the MicroLumin iOS SDK: the glasses app (B) talks to the backend over wifi itself, so the phone never needs Bluetooth. No SDK files live in this folder.

## Build to an iPhone
1. Open Xcode once and accept the license. When asked which platforms to install, tick **iOS** (or later: Settings › Components › iOS).
2. Run `sudo xcode-select -s /Applications/Xcode.app` in Terminal.
3. Add your Apple ID under Xcode › Settings › Accounts. A free account works; it becomes a "Personal Team".
4. On the iPhone, open Settings › Privacy & Security › Developer Mode, turn it on, and let the phone restart. (The option only appears after the phone has been plugged into Xcode once.)
5. Run `open ios/Worn.xcodeproj`. Click the Worn project, then target **Worn** › Signing & Capabilities. Leave "Automatically manage signing" checked and pick your Team.
   - If you see "bundle identifier not available", change `com.worn.phone` to something unique, e.g. `com.<yourname>.worn`.
6. Plug the iPhone in by cable, unlock it, and tap **Trust**. Pick the phone from the device menu at the top of the window (not a simulator).
7. Press ⌘R. The first build takes about a minute.
   - With a free account, the phone may block the app as an "Untrusted Developer". Allow it under Settings › General › VPN & Device Management › your Apple ID › Trust, then press ⌘R again.
8. In the app, allow **Local Network**. Then enter the laptop IP (from `ipconfig getifaddr en0` on the laptop). Phone and laptop must both be on the `event` wifi.
9. Free-account builds expire after 7 days. Rebuild Saturday morning to be safe.

## What it does
- Writing only (ASL was cut: the asl lesson is filtered out and ASL sessions from elsewhere are ignored).
- Pick a language (chips), then tap a phrase. That POSTs `/session` with `char_index 0` and the glasses show it.
- The lesson screen mirrors the glasses: the phrase as a strip of chars (current one highlighted, graded ones green or orange), the big char, romanization, and meaning. 🔊 plays the pronunciation on the phone.
- The phone polls `/session/result` every 0.7 s and shows the score plus feedback with a haptic. On a correct answer it auto-advances after 1.8 s: next char, then next phrase, then a lesson summary with scores.
- **Handoff:** it also polls `GET /session`. If anything else changes the session (`web/phone.html`, another phone), the app opens that lesson. Relaunching the app resumes the current session.
- Results only count if their `ts` is newer than the last one consumed and their `char`/`lang` match. So 谢谢's second 谢 never reuses the first grade.
- Controls: Prev / Replay (re-POSTs, so the glasses replay and the result clears) / Next, and **Grade with phone**, which takes a phone photo and POSTs `/grade`. That's the demo fallback if the glasses camera fails.
- Settings (tap the status dot): server address, grader-model status, auto-advance toggle.

## Tested
- Typechecks against the macOS SDK (`swiftc -typecheck`). iOS-only bits are behind `#if os(iOS)`.
- A headless harness drove `AppModel` + `API` against a private backend on :8765: connect, start, grade, auto-advance, stale-result filter, external handoff, external ASL ignored, lesson end, prev, offline. rapid Prev/Next taps, 13/13 passed.
- **Not yet built for iOS on this Mac** (no Xcode here). The camera picker, AVAudioSession, and keyboard modifiers are untested.

## TODO
- TODO(D): optional MLVisionM6SDK connection status (battery, connected), only if time allows. Fork the pattern from `04_Demo_Apps/MLDemo/GlassesSession.swift`; never paste SDK code here.
