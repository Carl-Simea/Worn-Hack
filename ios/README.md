# ios/ — Worn for iPhone (agent D)

SwiftUI, iOS 17+. The phone is the hub: it picks the lesson, drives auto-pacing, talks to the glasses through
MLVisionM6SDK (glasses build), and reports every step to the backend so `/live`, `/glasses` and `/mirror` mirror it.

There are **two builds of the same code** (`ios/Worn/`):

| Build | Open | Glasses | Use it for |
|---|---|---|---|
| **Glasses build** | `ios/build-glasses/WornGlasses.xcworkspace` (generated) | MLVisionM6SDK: connect, glasses camera, glasses speaker | The demo with the M6 |
| **Standalone** | `ios/Worn.xcodeproj` | none (Demo Mode: phone camera) | Simulator, backup phone, screenshots |

The SDK is confidential, so the glasses build is generated from the vendor kit and never committed
(`ios/.gitignore`). Both builds compile cleanly with Xcode 27.2 (verified 11/21: device build of the glasses
workspace, simulator build of the standalone project).

## Morning steps (glasses build on your iPhone)

1. **Xcode**: installed, license accepted. Plug the iPhone in, unlock it, tap **Trust**.
   iPhone: Settings › Privacy & Security › **Developer Mode** on (it restarts; the switch only appears after the phone
   has been connected to Xcode once).
2. **Generate the workspace** (≈10 s; re-run after every `git pull`):
   ```sh
   cd ~/worn && ios/scripts/make-glasses-build.sh
   ```
   Optional: `WORN_BUNDLE_ID=com.yourname.worn WORN_TEAM=<team id> ios/scripts/make-glasses-build.sh`.
3. **Open the workspace, not a project**:
   ```sh
   open ios/build-glasses/WornGlasses.xcworkspace
   ```
   Scheme **MLDemo** (the vendor's target name; the app is called **Worn** on the phone).
4. **Signing (free Apple ID works)**: Xcode › Settings › Accounts › add your Apple ID. Then target **MLDemo** ›
   Signing & Capabilities › keep *Automatically manage signing*, pick your **Team** (“Personal Team” is fine).
   If it says the bundle identifier is taken, change `com.worn.glasses` to something unique (e.g. `com.yourname.worn`).
5. **Build to the iPhone**: choose your iPhone in the device menu (not a simulator: the SDK is device-only) and press **⌘R**.
   First build ≈ 2–3 min (CocoaPods are checked in; no `pod install`).
6. **Trust the developer** (free Apple ID, first time): iPhone Settings › General › VPN & Device Management ›
   your Apple ID › Trust. Press ⌘R again.
7. **Pair the glasses**: charge them, long-press power. In Worn tap the status pill (top right) › **Find my glasses**
   › tap your pair. They say “Connected”. Next time: **Connect to …**. Keep Bluetooth on; allow Bluetooth, Local Network,
   Microphone, Speech Recognition and Camera when asked.
8. **Backend URL**: Settings (slider icon) › Lesson server › the laptop's IP (`ipconfig getifaddr en0` on the laptop;
   `:8000` is added). Phone, laptop and glasses on the same Wi-Fi. Glasses photos travel over Wi-Fi: if they don't
   arrive, put the glasses on the **phone's Personal Hotspot** and turn the phone's own Wi-Fi off (vendor note).
9. **Demo Mode** (no glasses, or the glasses misbehave): Settings › Demo Mode on. The phone camera watches the page
   (stand the phone over the paper; keep the page in the dashed box) and every event still reaches `/live`.

Standalone build instead: `open ios/Worn.xcodeproj`, scheme **Worn**, same signing steps, bundle id `com.worn.phone`.
It runs in the Simulator (a simulated pen writes each stroke so the whole loop can be watched).

## What it does

- **Home**: six script cards (你好 · नमस्ते · مرحبا · Привет · שלום · Γεια σου), each with its script name, one-line
  note and a progress ring; *Write your name*, *Daily 5*, *Help me write…*; streak and mastered count. No login.
- **Connect**: searching → connecting → connected → lost (reconnecting, with “use the phone instead”), Bluetooth off /
  not allowed, retry, Demo Mode toggle, server status.
- **Practice** (write along): big character on a 米字格 grid; done strokes in ink, the current stroke animating (true
  order for Mandarin, “suggested” for hand-authored scripts, traced glyph otherwise); romanization, meaning, 🔊 sound;
  a live black mirror of the glasses display; the phone camera with the writing box (Demo Mode).
- **Auto-pacing**: a frame every 1 s → on-device ink diff inside the writing box (tier 1, ≈1–5 ms on a 64×64 thumbnail)
  → new ink shows the next stroke immediately. Also advances on voice “next” or after 4 s (scaled by speed), whichever
  comes first, so it never gets stuck. Optional tier 2: `/stroke-match` per stroke (Settings). Last stroke + 1.3 s of
  calm → final photo → `/grade` (tier 3).
- **Results**: score, a goofy line + sound from `content/reactions.json` (streak lines at 3/5/10), the one-line fix
  spoken when it's wrong, rainbow confetti on success, milestone banners from `content/milestones.json` (first letter,
  first word, first mastered, first name, all six). The tutor's `next.action` decides retry vs. move on; otherwise one
  slower retry, then move on.
- **Dictation** (“From memory”): the word is spoken, the character hidden; write it, put the pen down (or say “check”).
- **Voice, hands-free** (Apple Speech, on-device): next · again · slower · check · “switch to Hebrew” ·
  “help me write good luck in Greek” → translation (native, romanization, back-translation) → guided writing.
- **Write your name**: instant on-device spelling in five scripts from `content/names/*.json`, replaced by the server's
  `/name` answer when it arrives.
- **Daily 5** (`/review`, on-device fallback), **Journal** (`/journal`, your photos per character over time).
- **Progress**: Seen → Practiced → Mastered per character, rings per language, adaptive animation speed (slower after
  misses, quicker once mastered). Stored on the phone.
- **Handoff**: a lesson started on another device (web picker, /live) opens on the phone at the same character.
- **Debug overlay** (Settings): last/avg ms for capture, tier 1, tier 2, tier 3 and pen→next, plus the last events.

## Events posted to `POST /event`

`app.open` · `app.connected` · `app.offline` · `mode.demo` · `glasses.status` · `listening` · `practice.start` ·
`session.start` · `glasses.show` (`stroke` 0-based, `stroke_number`, `stroke_count`, `trigger` ink|voice|timeout|manual) ·
`glasses.frame` (glasses photo timings) · `ink` (`tier1_ms`, `pen_to_next_ms`) · `stroke_match` · `grade.start` ·
`grade` · `reaction` · `confetti` · `milestone` · `speak` · `voice` · `again` · `slower` · `compose` · `name` ·
`handoff` · `practice.finished` · `practice.stop`.

## Tests

```sh
ios/Tests/run-core-tests.sh        # stroke parsing (all content/strokes), ink diff, pacer, voice parser, name speller
```
Simulator, end to end: run the backend, then
`xcrun simctl launch booted com.worn.phone -wornOpen practice:mandarin:hello` (deep links: `lesson:LANG`,
`practice:LANG:ITEM[:dictation]`, `compose:TEXT:LANG`, `name:NAME`, `daily`, `journal:LANG`, `connect`).
Voice without a microphone: add `-wornSay "switch to Hebrew" -wornSayAfter 9` (runs the phrase through the same parser).
Screenshots: `screenshots/ios/`.

## Compile / runtime risks I couldn't verify (no glasses or iPhone here)

- **Glasses camera round trip** (`SDKGlassesLink.takePhoto`): open camera app 25 → list files → Wi-Fi download →
  confirm + delete. Built from MLDemo's exact calls, but the timing (likely 2–5 s per photo) and the file names are
  untested. If a photo doesn't arrive in ~15 s the loop just carries on (voice/timeout still advance) and the final
  grade falls back to the phone camera.
- **Glasses display**: MLVisionM6SDK has no call to draw on the glasses. What the glasses show comes from the
  backend's `/glasses` page following `/session` + `/event`; the phone's black “Glasses view” mirrors it.
- **Glasses button**: the SDK exposes no button event that I could find, so pacing is hands-free (ink, voice, timeout).
- **Glasses speaker** (`playTTS(forAssistant:…, modelId: "namibox")`, as in MLDemo): English lines only;
  pronunciation clips play on the phone.
- **SDK delegate**: `sdkInit(withDelegate:)` gets the app's root view controller (MLDemo passes its home view controller).
- Script fonts: Noto Sans SC / Devanagari / Naskh Arabic / Hebrew / Sans (Greek, Cyrillic), subset and bundled
  (`Worn/Resources/Fonts`, SIL OFL 1.1, `OFL.txt`). Characters outside the subset fall back to the system font.
- Voice recognition and the phone camera are untested on a real device tonight (they're standard Apple APIs); the
  Simulator runs with voice off and a simulated page.
