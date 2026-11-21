import AVFoundation
import Foundation
import Observation

/// All phone-side state. The backend holds the one shared session; this mirrors it.
///
/// Handoff model: the phone POSTs /session, the glasses pick it up by polling, the glasses POST /grade,
/// and this class picks the result up by polling /session/result. If anything else changes the session
/// (the web backup controller, another phone), the poll adopts it, so the phone always shows what the glasses show.
@MainActor
@Observable
final class AppModel {
    enum Link: Equatable { case unknown, ok, down(String) }
    enum Status: Equatable { case waiting, grading, correct(GradeResult), fix(GradeResult), lessonDone }

    static let autoAdvanceDelay: Duration = .milliseconds(1800)
    static let pollInterval: Duration = .milliseconds(700)

    var serverAddress: String {
        didSet { UserDefaults.standard.set(serverAddress, forKey: "server"); reconnect() }
    }
    var autoAdvance: Bool {
        didSet { UserDefaults.standard.set(autoAdvance, forKey: "autoAdvance") }
    }

    private(set) var link: Link = .unknown
    private(set) var modelReady: Bool?
    private(set) var lessons: [Lesson] = []
    private(set) var session: SessionState?
    private(set) var status: Status = .waiting
    private(set) var lastError: String?
    /// Best score per "lang/phrase/charIndex", shown on the picker and the lesson strip.
    private(set) var best: [String: Int] = [:]

    /// Drives the lesson screen. Cleared by Back; set again if the session changes elsewhere.
    var showingLesson = false

    private var api: API?
    private var pollTask: Task<Void, Never>?
    private var advanceTask: Task<Void, Never>?
    /// Newest result ts we've already consumed. Anything at or below it is stale (e.g. the previous 谢 of 谢谢).
    private var seenTs: Double = 0
    private var knownVersion: Int = -1
    private var player: AVPlayer?

    init() {
        let d = UserDefaults.standard
        serverAddress = d.string(forKey: "server") ?? ""
        autoAdvance = d.object(forKey: "autoAdvance") as? Bool ?? true
        reconnect()
    }

    var hasServer: Bool { !serverAddress.trimmingCharacters(in: .whitespaces).isEmpty }

    func lesson(for lang: String) -> Lesson? { lessons.first { $0.lang == lang } }

    var currentLesson: Lesson? { session.flatMap { lesson(for: $0.lang) } }

    var currentPhrase: Phrase? {
        guard let s = session else { return nil }
        return currentLesson?.phrases.first { $0.id == s.phraseId }
    }

    static func key(_ lang: String, _ phrase: String, _ index: Int) -> String { "\(lang)/\(phrase)/\(index)" }

    func bestScore(lang: String, phrase: Phrase) -> Int? {
        let scores = phrase.chars.indices.compactMap { best[Self.key(lang, phrase.id, $0)] }
        guard !scores.isEmpty, scores.count == phrase.chars.count else { return nil }
        return scores.reduce(0, +) / scores.count
    }

    // MARK: connection

    func reconnect() {
        pollTask?.cancel()
        lessons = []
        link = .unknown
        guard hasServer else { api = nil; return }
        do { api = try API(baseString: serverAddress) } catch {
            api = nil; link = .down(error.localizedDescription); return
        }
        pollTask = Task { [weak self] in await self?.pollLoop() }
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await tick()
            try? await Task.sleep(for: Self.pollInterval)
        }
    }

    private func tick() async {
        guard let api else { return }
        do {
            if lessons.isEmpty {
                // ASL is cut: drop the asl lesson and anything without characters to write.
                lessons = try await api.content().filter { $0.lang != "asl" }.map { l in
                    Lesson(lang: l.lang, name: l.name, rtl: l.rtl, phrases: l.phrases.filter(\.canWrite))
                }.filter { !$0.phrases.isEmpty }
                modelReady = try? await api.health()?.modelReady
                seenTs = (try? await api.result())?.ts ?? 0  // don't replay a result from before we connected
            }
            if let remote = try await api.currentSession(), let v = remote.version, v > knownVersion, remote.mode == .write {
                adopt(remote, fromServer: true)
            }
            if let s = session, let r = try await api.result() {
                consume(r, for: s)
            }
            link = .ok
        } catch is CancellationError {
        } catch let e as URLError where e.code == .cancelled {
        } catch {
            link = .down(error.localizedDescription)
        }
    }

    // MARK: session control

    func start(lang: String, phraseId: String, charIndex: Int = 0) {
        guard let api else { return }
        advanceTask?.cancel()
        Task {
            do {
                let s = try await api.startSession(SessionRequest(lang: lang, phraseId: phraseId, charIndex: charIndex, mode: .write))
                adopt(s, fromServer: false)
                lastError = nil
                link = .ok
            } catch {
                lastError = "Couldn't reach the glasses server: \(error.localizedDescription)"
            }
        }
    }

    private func adopt(_ s: SessionState, fromServer: Bool) {
        if let v = s.version { knownVersion = max(knownVersion, v) }
        let changed = s != session
        session = s
        if changed { status = .waiting }
        if fromServer && changed { showingLesson = true }
        if !fromServer { showingLesson = true }
    }

    private func consume(_ r: GradeResult, for s: SessionState) {
        guard r.ts > seenTs else { return }
        // Results are posted with the char the glasses graded; ignore anything for a different char.
        if let c = r.char, c != s.char { return }
        if let l = r.lang, l != s.lang { return }
        seenTs = r.ts
        let k = Self.key(s.lang, s.phraseId, s.charIndex)
        best[k] = max(best[k] ?? 0, r.scoreInt)
        if r.correct {
            status = .correct(r)
            scheduleAdvance()
        } else {
            status = .fix(r)
        }
    }

    private func scheduleAdvance() {
        advanceTask?.cancel()
        guard autoAdvance, showingLesson else { return }
        advanceTask = Task { [weak self] in
            try? await Task.sleep(for: Self.autoAdvanceDelay)
            guard !Task.isCancelled else { return }
            self?.next()
        }
    }

    /// Next char, then next phrase. After the last phrase, show the lesson summary.
    func next() {
        guard let s = session, let lesson = currentLesson else { return }
        if s.charIndex + 1 < s.totalChars {
            start(lang: s.lang, phraseId: s.phraseId, charIndex: s.charIndex + 1)
            return
        }
        guard let i = lesson.phrases.firstIndex(where: { $0.id == s.phraseId }) else { return }
        if i + 1 < lesson.phrases.count {
            start(lang: s.lang, phraseId: lesson.phrases[i + 1].id)
        } else {
            advanceTask?.cancel()
            status = .lessonDone
        }
    }

    func previous() {
        guard let s = session, let lesson = currentLesson else { return }
        if s.charIndex > 0 {
            start(lang: s.lang, phraseId: s.phraseId, charIndex: s.charIndex - 1)
        } else if let i = lesson.phrases.firstIndex(where: { $0.id == s.phraseId }), i > 0 {
            start(lang: s.lang, phraseId: lesson.phrases[i - 1].id)
        }
    }

    /// Re-POST the same session: the glasses replay the animation + audio, and the old result is cleared.
    func replayOnGlasses() {
        guard let s = session else { return }
        start(lang: s.lang, phraseId: s.phraseId, charIndex: s.charIndex)
    }

    func restartLesson() {
        guard let s = session, let first = currentLesson?.phrases.first else { return }
        start(lang: s.lang, phraseId: first.id)
    }

    func leaveLesson() {
        advanceTask?.cancel()
        showingLesson = false
    }

    // MARK: phone-side extras

    func playAudioOnPhone() {
        guard let path = session?.audioUrl, let url = api?.url(path) else { return }
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setCategory(.playback)
        #endif
        player = AVPlayer(url: url)
        player?.play()
    }

    /// Fallback if the glasses camera misbehaves during the demo: grade a phone photo instead.
    func gradeWithPhonePhoto(_ jpeg: Data) {
        guard let api, let s = session, let char = s.char else { return }
        advanceTask?.cancel()
        status = .grading
        Task {
            do {
                let r = try await api.grade(jpeg: jpeg, char: char, lang: s.lang)
                if session == s { consume(r, for: s) }
            } catch {
                if session == s { status = .waiting }
                lastError = "Grading failed: \(error.localizedDescription)"
            }
        }
    }

    func clearError() { lastError = nil }
}
