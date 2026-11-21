# REMAINING — agent D (iOS)

Updated 2026-11-21 ~03:00. Everything below is pushed to `origin/main`.

## Done and verified

- **App** (`ios/Worn/`, SwiftUI, iOS 17+): Home (6 script cards, rings, streak), Connect (searching / connecting /
  connected / lost / Bluetooth off), Practice with auto-pacing, Dictation, Help me write (compose), Write your name,
  Daily 5, Journal, Settings (backend URL, Demo Mode, voice, debug overlay), confetti, reactions + sounds from content,
  milestones, Seen → Practiced → Mastered, adaptive speed, handoff from other devices.
- **Builds**: standalone `ios/Worn.xcodeproj` builds and runs in the iOS 27.2 Simulator; the **glasses build**
  (`ios/scripts/make-glasses-build.sh` → `ios/build-glasses/WornGlasses.xcworkspace`, vendor Pods + MLVisionM6SDK +
  Worn) compiles for a real iPhone with no errors or warnings in Worn's code, and `SDKGlassesLink` is linked in.
- **End to end in the Simulator against the real backend + real vision model**: practice 你好 (simulated pen →
  tier-1 ink detection in 1–5 ms → next stroke → `/grade` 90 → confetti + "Nailed it!"), Hebrew שלום (RTL, suggested
  strokes), Greek νερό via handoff, dictation 水 → "Mastered" milestone, summary, journal photos, Daily 5 from `/review`,
  name spelling, `/live/state` mirroring every step (0-based strokes, phases, latencies). Screenshots: `screenshots/ios/`.
- **Core tests**: `ios/Tests/run-core-tests.sh` (all content stroke files parse, ink diff, pacer never gets stuck,
  voice commands, name speller 44/58 exact vs content examples). All pass.

## How to demo (2:15)

1. Laptop: backend on :8000 (A), `/live` on the big screen. Close Xcode and the Simulator (they slow the GPU).
2. iPhone: open **Worn** (glasses build). Status pill → connect the glasses (or Settings › Demo Mode on, phone on a
   stand over the paper).
3. Tap **Mandarin** → 你好 → write along. Each stroke appears; write it; the next one follows your pen (or say
   “next”, or wait 4 s). Last stroke → grade → confetti + a goofy line. `/live` shows it all.
4. Show-offs: say “switch to Hebrew”; say “help me write good luck in Greek”; **Write your name**; **From memory**
   (dictation); start a lesson from the web page and watch the phone pick it up (handoff).
5. Backup if anything misbehaves: Demo Mode (phone camera) — or the web `/app` on any phone.

Morning setup (signing, free Apple ID, trust, pairing, backend URL): **`ios/README.md`**.

## Needs real glasses / a real iPhone to verify

- Glasses photo round trip (`SDKGlassesLink.takePhoto`: camera app 25 → file list → Wi-Fi download). Built from
  MLDemo's exact calls; timing per photo unknown (probably 2–5 s, so ink detection with glasses is slower than with the
  phone camera; voice/timeout keep it moving). If photos don't arrive: glasses on the phone's Personal Hotspot.
- Pairing/connection through MLDemo's `GlassesSession` (vendor code, unchanged).
- Glasses speaker lines (`playTTS`, English only).
- Voice commands and the phone camera on a real device (standard Apple APIs; the Simulator has no usable mic/camera).

## Known limits (honest)

- The SDK has no call to draw on the glasses display, and no button event. What the glasses show is the backend's
  `/glasses` page following `/session` + `/event`; pacing is hands-free (ink / voice / timeout).
- "Write your name" offline spelling is approximate (English vowels are ambiguous); the server's `/name` replaces it
  when it answers.
- Script fonts: bundled Noto subsets (Chinese: lesson characters + the 3,755 most common hanzi); anything outside falls back to the system font.
