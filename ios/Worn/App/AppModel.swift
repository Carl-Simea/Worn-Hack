import Foundation
import Observation

/// App-wide state. The backend holds the one shared session (the glasses page and the judge site follow it);
/// this class keeps the phone in sync and reports everything that happens via POST /event.
@MainActor
@Observable
final class AppModel {
    enum Link: Equatable { case unknown, ok, down(String) }

    // MARK: settings

    var serverAddress: String {
        didSet { UserDefaults.standard.set(serverAddress, forKey: "server"); reconnect() }
    }
    /// No glasses: phone camera for photos, phone speaker for lines. Still posts every event.
    var demoMode: Bool {
        didSet { UserDefaults.standard.set(demoMode, forKey: "demoMode"); report("mode.demo", ["on": .bool(demoMode)]) }
    }
    var showDebug: Bool { didSet { UserDefaults.standard.set(showDebug, forKey: "debug") } }
    var voiceEnabled: Bool {
        didSet {
            UserDefaults.standard.set(voiceEnabled, forKey: "voice")
            Task { voiceEnabled ? await voice.start() : voice.stop() }
        }
    }
    var autoAdvance: Bool { didSet { UserDefaults.standard.set(autoAdvance, forKey: "autoAdvance") } }
    /// Optional tier 2: confirm each detected stroke with POST /stroke-match (off unless the backend has it).
    var useStrokeMatch: Bool { didSet { UserDefaults.standard.set(useStrokeMatch, forKey: "strokeMatch") } }

    // MARK: state

    private(set) var link: Link = .unknown
    private(set) var health: Health?
    private(set) var lessons: [Lesson] = []
    private(set) var reactions = Reactions.fallback
    private(set) var milestones = Milestones.fallback
    /// content/names/*.json, used when /name can't answer.
    private(set) var nameTables: [String: NameTable] = [:]
    /// Scripts written correctly since launch (for the "all six" milestone).
    var langsCorrectThisSitting: Set<String> = []
    private(set) var glassesStatus: GlassesStatus = .noSDK
    private(set) var nearbyGlasses: [GlassesDevice] = []
    var progress = ProgressBook.load() { didSet { progress.save() } }

    /// Local mirror of what we've reported (debug overlay).
    private(set) var eventLog: [(ts: Date, type: String, summary: String)] = []
    private(set) var latency = Latency()

    /// The practice run on screen, if any (voice commands go to it).
    var practice: PracticeEngine?
    /// The feedback window, while open (screenshot + context are saved when it opens).
    var feedbackDraft: FeedbackDraft?
    /// Navigation from voice ("switch to …", "help me write …").
    var route: [Route] = []
    var pendingCompose: (text: String, lang: String?)?
    /// Practice opened from outside a screen (deep link / voice); RootView presents it.
    var pendingLaunch: PracticeLaunch?
    /// Bumped to ask any open practice screen to close (voice navigation).
    private(set) var closePracticeRequest = 0

    let glasses: GlassesLink
    let camera = PhoneCamera()
    let voice = VoiceListener()
    @ObservationIgnored lazy var assistant: Assistant = Assistant(app: self)
    private(set) var api: API?
    private var pollTask: Task<Void, Never>?
    private var handoffTask: Task<Void, Never>?
    /// Session versions this phone started; anything newer is a handoff from another device.
    private var ownVersions: Set<Int> = []
    private var lastSessionVersion: Int?
    /// Shown briefly when a lesson arrives from another device.
    private(set) var handoffNote: String?
    private var strokeCache: [String: StrokeData] = [:]
    private var strokeMisses: Set<String> = []

    /// The demo laptop on the venue Wi-Fi (11/21). A value typed in Settings wins over this.
    static let defaultServer = "http://10.0.221.236:8000"

    init() {
        let d = UserDefaults.standard
        let saved = d.string(forKey: "server")?.trimmingCharacters(in: .whitespaces) ?? ""
        serverAddress = saved.isEmpty ? Self.defaultServer : saved
        demoMode = d.object(forKey: "demoMode") as? Bool ?? false
        showDebug = d.object(forKey: "debug") as? Bool ?? false
        #if targetEnvironment(simulator)
        voiceEnabled = d.object(forKey: "voice") as? Bool ?? false   // no mic worth using; avoids the prompt
        #else
        voiceEnabled = d.object(forKey: "voice") as? Bool ?? true
        #endif
        autoAdvance = d.object(forKey: "autoAdvance") as? Bool ?? true
        useStrokeMatch = d.object(forKey: "strokeMatch") as? Bool ?? false
        glasses = GlassesLinkFactory.make()
        glasses.onChange = { [weak self] in self?.glassesChanged() }
        voice.onCommand = { [weak self] cmd in self?.handle(cmd) }
        voice.onStateChange = { [weak self] state in
            self?.report("listening", ["on": .bool(state == .listening)])
        }
        reconnect()
    }

    /// Called once the window exists (the SDK wants a view controller as its delegate).
    func onLaunch() {
        glasses.start()
        glassesChanged()
        // Without the SDK there are no glasses to wait for: go straight to Demo Mode.
        if glassesStatus == .noSDK && UserDefaults.standard.object(forKey: "demoMode") == nil { demoMode = true }
        if voiceEnabled { Task { await voice.start() } }
        report("app.open", ["demo_mode": .bool(demoMode), "glasses": .string(glassesStatus.title)])
        if let open = UserDefaults.standard.string(forKey: "wornOpen") { Task { await deepLink(open) } }
        // Test hook for the voice path (no microphone in the Simulator): `-wornSay "switch to Hebrew" -wornSayAfter 9`
        if let phrase = UserDefaults.standard.string(forKey: "wornSay") {
            let delay = UserDefaults.standard.object(forKey: "wornSayAfter") as? Double ?? 8
            Task { [weak self] in
                try? await Task.sleep(for: .seconds(delay))
                if let cmd = VoiceCommandParser.parse(phrase) { self?.handle(cmd) }
            }
        }
    }

    /// Launch argument `-wornOpen <route>` (demo shortcuts, screenshots, end-to-end runs):
    /// lesson:LANG · practice:LANG:ITEM[:dictation] · compose:TEXT:LANG · name · daily · journal:LANG · connect
    func deepLink(_ spec: String) async {
        for _ in 0..<120 where lessons.isEmpty { try? await Task.sleep(for: .milliseconds(250)) }
        let p = spec.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        switch p.first {
        case "lesson" where p.count > 1: route = [.lesson(p[1])]
        case "practice" where p.count > 2:
            guard let lesson = lesson(p[1]), let phrase = lesson.phrases.first(where: { $0.id == p[2] }) else { return }
            route = [.lesson(p[1])]
            try? await Task.sleep(for: .milliseconds(700))   // let the push finish before presenting the cover
            let mode: PracticeMode = p.count > 3 && p[3] == "dictation" ? .dictation : .write
            pendingLaunch = PracticeLaunch(items: PracticeItem.all(lang: p[1], phrase: phrase), mode: mode, title: phrase.meaning ?? phrase.text)
        case "compose":
            pendingCompose = (p.count > 1 ? p[1] : "good luck", p.count > 2 ? p[2] : nil)
            route = [.compose]
        case "name":
            if p.count > 1 { UserDefaults.standard.set(p[1], forKey: "name") }
            route = [.name]
        case "daily": route = [.daily]
        case "journal" where p.count > 1: route = [.journal(p[1])]
        case "connect": route = [.connect]
        default: break
        }
    }

    var hasServer: Bool { !serverAddress.trimmingCharacters(in: .whitespaces).isEmpty }

    /// Where photos come from right now.
    var photoSource: PhotoSource {
        if demoMode || !glassesStatus.isConnected { return .phone }
        return .glasses
    }

    func lesson(_ lang: String) -> Lesson? { lessons.first { $0.lang == lang } }

    // MARK: backend

    func reconnect() {
        pollTask?.cancel()
        link = .unknown
        guard hasServer else { api = nil; return }
        do { api = try API(baseString: serverAddress) } catch { api = nil; link = .down(error.localizedDescription); return }
        Sounds.shared.api = api
        strokeCache = [:]; strokeMisses = []
        lastSessionVersion = nil
        handoffTask?.cancel()
        handoffTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.checkHandoff()
                try? await Task.sleep(for: .seconds(1))
            }
        }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                // Fast retries until connected, then a slow heartbeat.
                let ok = self?.link == .ok && !(self?.lessons.isEmpty ?? true)
                try? await Task.sleep(for: .seconds(ok ? 6 : 1.5))
            }
        }
    }

    private var misses = 0

    /// Lessons come straight from /content (cheap). /health also asks the model server and can be slow while a
    /// grade is running, so one slow heartbeat never flips the app to "offline": it takes two misses in a row.
    private func refresh() async {
        guard let api else { return }
        do {
            if lessons.isEmpty {
                lessons = try await api.content().filter { !$0.phrases.isEmpty && $0.lang != "asl" }
                link = .ok
                misses = 0
                await loadOptionalContent(api)
                report("app.connected", ["langs": .int(lessons.count)])
            }
            health = try await api.health()
            link = .ok
            misses = 0
        } catch {
            misses += 1
            guard misses >= 2 || lessons.isEmpty else { return }
            if case .ok = link { report("app.offline", ["error": .string(error.localizedDescription)]) }
            link = .down(error.localizedDescription)
        }
    }

    private func loadOptionalContent(_ api: API) async {
        if let d = try? await api.staticFile("reactions.json"), let r = try? JSONDecoder().decode(Reactions.self, from: d), !r.kinds.isEmpty {
            reactions = r
        }
        if let d = try? await api.staticFile("milestones.json"), let m = try? JSONDecoder().decode(Milestones.self, from: d), !m.byLang.isEmpty {
            milestones = m
        }
        Sounds.shared.preload(Array(Set(reactions.kinds.values.flatMap { [$0.sound, $0.then].compactMap { $0 } + ($0.altSounds ?? []) })))
        for script in ["devanagari", "arabic", "cyrillic", "hebrew", "greek"] {
            if let d = try? await api.staticFile("names/\(script).json"), let t = try? JSONDecoder().decode(NameTable.self, from: d) {
                nameTables[t.lang] = t
            }
        }
    }

    /// Offline "Write your name": spell it by sound with the team's tables.
    func offlineName(_ name: String) -> [NameResponse.Rendering] {
        NameResponse.scriptKeys.compactMap { k in
            guard let t = nameTables[k.lang] else { return nil }
            let spelled = t.spell(name)
            return spelled.isEmpty ? nil : NameResponse.Rendering(lang: k.lang, text: spelled, offline: true)
        }
    }

    /// Stroke data for a character: content/strokes/{lang}/{codepoint hex}.json (hanzi-writer) or .svg (centerlines).
    func strokes(lang: String, char: String, hint: String? = nil) async -> StrokeData? {
        let key = "\(lang)/\(char)"
        if let s = strokeCache[key] { return s }
        guard let api, !strokeMisses.contains(key) else { return nil }
        let hex = char.unicodeScalars.map { String($0.value, radix: 16) }.joined(separator: "-")
        var candidates = [hint].compactMap { $0 }
        candidates += ["/static/content/strokes/\(lang)/\(hex).json", "/static/content/strokes/\(lang)/\(hex).svg"]
        var onlyNotFound = true
        for path in candidates {
            let data: Data
            do { data = try await api.staticFile(path) } catch APIError.notFound { continue } catch {
                onlyNotFound = false   // timeout / offline: try again next time, don't remember it as "no strokes"
                continue
            }
            let parsed: StrokeData? = path.hasSuffix(".svg") ? StrokeData.svgCenterlines(data) : try? StrokeData.hanziWriter(data)
            if let parsed, parsed.count > 0 { strokeCache[key] = parsed; return parsed }
        }
        if onlyNotFound { strokeMisses.insert(key) }
        return nil
    }

    // MARK: handoff (a lesson started on another device opens here)

    func noteOwnSession(_ s: SessionState) {
        if let v = s.version { ownVersions.insert(v); lastSessionVersion = max(lastSessionVersion ?? v, v) }
    }

    private func checkHandoff() async {
        guard let api, !lessons.isEmpty, let s = try? await api.currentSession(), let v = s.version else { return }
        guard let last = lastSessionVersion else { lastSessionVersion = v; return }   // first look: just remember
        guard v > last else { return }
        lastSessionVersion = v
        guard !ownVersions.contains(v) else { return }
        // Don't yank an active practice away; only follow when the phone is free.
        if let p = practice, p.phase != .finished { report("handoff.ignored", ["reason": "practicing", "char": .opt(s.char)]); return }
        guard let phrase = lesson(s.lang)?.phrases.first(where: { $0.id == s.id }) ?? s.asPhrase, phrase.canWrite else { return }
        let start = min(max(0, s.charIndex), phrase.chars.count - 1)
        let items = Array(PracticeItem.all(lang: s.lang, phrase: phrase).dropFirst(start))
        let mode: PracticeMode = PracticeMode(rawValue: s.mode ?? "write") ?? .write
        handoffNote = "Picked up \(phrase.meaning ?? phrase.text) from another device"
        report("handoff", ["lang": .string(s.lang), "item": .string(phrase.id), "char_index": .int(start), "version": .int(v)])
        pendingLaunch = PracticeLaunch(items: items, mode: mode, title: phrase.meaning ?? phrase.text, adoptedVersion: v)
        Task { try? await Task.sleep(for: .seconds(4)); handoffNote = nil }
    }

    // MARK: events (the judge site mirrors these)

    func report(_ type: String, _ data: [String: JSONValue] = [:]) {
        let summary = data.sorted { $0.key < $1.key }.prefix(4).map { "\($0.key)=\(Self.short($0.value))" }.joined(separator: " ")
        eventLog.append((Date(), type, summary))
        if eventLog.count > 60 { eventLog.removeFirst(eventLog.count - 60) }
        guard let api else { return }
        let body = EventBody(type: type, data: data)
        Task.detached { try? await api.event(body) }
    }

    private static func short(_ v: JSONValue) -> String {
        switch v {
        case .string(let s): return String(s.prefix(18))
        case .number(let n): return n == n.rounded() ? String(Int(n)) : String(format: "%.2f", n)
        case .bool(let b): return b ? "yes" : "no"
        case .null: return "–"
        case .array(let a): return "[\(a.count)]"
        case .object(let o): return "{\(o.count)}"
        }
    }

    func recordLatency(_ tier: Latency.Tier, ms: Int) { latency.record(tier, ms: ms) }

    // MARK: glasses

    private func glassesChanged() {
        let old = glassesStatus
        glassesStatus = glasses.status
        nearbyGlasses = glasses.nearby
        if old != glassesStatus {
            report("glasses.status", ["status": .string(glassesStatus.title), "connected": .bool(glassesStatus.isConnected)])
            if glassesStatus.isConnected && !old.isConnected { Sounds.shared.effect(.chime) }
        }
    }

    /// Say a line through the glasses if they're on, otherwise the phone. Voice commands pause meanwhile.
    func say(_ text: String) {
        report("speak", ["text": .string(text), "via": .string(photoSource == .glasses ? "glasses" : "phone")])
        if photoSource == .glasses {
            glasses.speak(text)
        } else {
            voice.pause()
            Sounds.shared.say(text)
            Task { [voice] in
                try? await Task.sleep(for: .seconds(min(4, 0.9 + Double(text.count) * 0.055)))
                voice.resume()
            }
        }
    }

    // MARK: voice

    func handle(_ cmd: VoiceCommand) {
        report("voice", ["command": .string("\(cmd)"), "heard": .string(voice.lastHeard)])
        switch cmd {
        case .next, .back, .again, .slower, .check:
            practice?.voice(cmd)
        case .switchTo(let lang):
            guard lesson(lang) != nil else { return }
            navigateAfterClosingPractice { $0.route = [.lesson(lang)] }
        case .helpMeWrite(let message, let lang):
            let target = lang ?? practice?.current?.lang
            navigateAfterClosingPractice {
                $0.pendingCompose = (message, target)
                $0.route = [.compose]
            }
        }
    }

    /// Voice navigation: close an open practice first (it's a full-screen cover), then move.
    private func navigateAfterClosingPractice(_ go: @escaping (AppModel) -> Void) {
        guard practice != nil || pendingLaunch != nil else { go(self); return }
        practice?.stop()
        pendingLaunch = nil
        closePracticeRequest += 1
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(650))
            guard let self else { return }
            go(self)
        }
    }
}

enum PhotoSource: String { case glasses, phone }

enum Route: Hashable {
    case lesson(String)
    case compose
    case name
    case daily
    case journal(String)
    case connect
}

/// Rolling per-tier latency for the debug overlay.
struct Latency: Equatable {
    enum Tier: String, CaseIterable { case capture, inkDiff = "tier1", strokeMatch = "tier2", grade = "tier3", nextStroke = "next" }
    private(set) var last: [Tier: Int] = [:]
    private(set) var avg: [Tier: Double] = [:]

    mutating func record(_ t: Tier, ms: Int) {
        last[t] = ms
        avg[t] = avg[t].map { $0 * 0.7 + Double(ms) * 0.3 } ?? Double(ms)
    }
}
