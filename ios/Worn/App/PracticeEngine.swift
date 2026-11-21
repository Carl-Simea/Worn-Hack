import CoreGraphics
import Foundation
import ImageIO
import Observation

struct PracticeItem: Hashable, Identifiable, Sendable {
    let lang: String
    let phrase: Phrase
    let charIndex: Int
    /// Not in the lesson files (compose / name): sent to /session with its text and chars.
    let adHoc: Bool

    var char: String { phrase.chars[charIndex] }
    var id: String { "\(lang)/\(phrase.id)/\(charIndex)" }

    static func all(lang: String, phrase: Phrase, adHoc: Bool = false) -> [PracticeItem] {
        phrase.chars.indices.map { PracticeItem(lang: lang, phrase: phrase, charIndex: $0, adHoc: adHoc) }
    }
}

/// One practice run: a queue of characters, each written on paper with auto-paced strokes, then graded.
@MainActor
@Observable
final class PracticeEngine {
    enum Phase: Equatable {
        case starting
        case writing
        case checking
        case result(GradeResult)
        case failed(String)
        case finished
    }

    struct Outcome: Identifiable, Equatable {
        let item: PracticeItem
        let result: GradeResult?
        var id: String { item.id }
    }

    let mode: PracticeMode
    let title: String
    private(set) var queue: [PracticeItem]
    private(set) var index = 0
    private(set) var phase: Phase = .starting
    private(set) var strokes: StrokeData?
    private(set) var pacer = Pacer(strokeCount: 1)
    /// 1-based stroke currently being demonstrated (phone + glasses).
    private(set) var shownStroke = 1
    /// Bumps on every stroke change so the animation restarts even on "again".
    private(set) var strokeEpoch = 0
    private(set) var lastTrigger: Pacer.Trigger?
    private(set) var reactionLine: String?
    private(set) var newMilestone: EarnedMilestone?
    private(set) var streak = 0
    private(set) var confettiBurst = 0
    private(set) var outcomes: [Outcome] = []
    private(set) var lastInk: InkDiff.Result?
    private(set) var lastPhoto: CGImage?
    private(set) var now = Date()
    private(set) var attemptsOnCurrent = 0
    /// Dictation: the answer stays hidden until graded.
    var revealed: Bool { mode != .dictation || { if case .result = phase { return true }; return false }() }

    private unowned let app: AppModel
    private var ink = InkDiff()
    private var loopTask: Task<Void, Never>?
    private var tickTask: Task<Void, Never>?
    private var advanceTask: Task<Void, Never>?
    private var strokeShownAt = Date()
    private var dictationInkAt: Date?
    private var dictationStartedAt = Date()
    private var running = false

    /// "Write your name" run (for the first_name milestone).
    let isName: Bool

    init(app: AppModel, items: [PracticeItem], mode: PracticeMode, title: String, isName: Bool = false) {
        self.isName = isName
        self.app = app
        self.queue = items
        self.mode = mode
        self.title = title
    }

    var current: PracticeItem? { index < queue.count ? queue[index] : nil }
    var lesson: Lesson? { current.flatMap { app.lesson($0.lang) } }
    var speed: Double { pacer.speed }
    var hasStrokeOrder: Bool { (strokes?.count ?? 0) > 0 }
    var isLast: Bool { index >= queue.count - 1 }

    // MARK: lifecycle

    func start() {
        guard !running else { return }
        running = true
        app.practice = self
        app.report("practice.start", ["mode": .string(mode.rawValue), "title": .string(title), "count": .int(queue.count)])
        Task { await begin(index: 0) }
        tickTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(250))
                self?.tick()
            }
        }
    }

    func stop() {
        running = false
        loopTask?.cancel(); tickTask?.cancel(); advanceTask?.cancel()
        if app.practice === self { app.practice = nil }
        app.camera.stop()
        app.report("practice.stop", ["done": .int(outcomes.count)])
    }

    private func begin(index i: Int) async {
        advanceTask?.cancel()
        loopTask?.cancel()
        guard running else { return }
        guard i < queue.count else { finish(); return }
        index = i
        attemptsOnCurrent = 0
        let item = queue[i]
        phase = .starting
        reactionLine = nil
        newMilestone = nil
        app.progress.markSeen(item.lang, item.char)

        // Tell the backend: the glasses page and the live view follow /session.
        // Ad-hoc items (a name spelled on the phone) aren't on the server; they're reported as events instead.
        var hint = item.phrase.strokeURL(at: item.charIndex)
        if let api = app.api, !item.adHoc {
            let req = SessionRequest(lang: item.lang, itemId: item.phrase.id, charIndex: item.charIndex, mode: mode)
            if let s = try? await api.startSession(req) { hint = s.strokeUrl ?? hint }
        }
        strokes = await app.strokes(lang: item.lang, char: item.char, hint: hint)
        guard running, index == i else { return }

        let speed = app.progress.progress(item.lang, item.char).animationSpeed
        resetPacer(speed: speed)
        app.report("session.start", [
            "lang": .string(item.lang), "item": .string(item.phrase.id), "char": .string(item.char),
            "char_index": .int(item.charIndex), "total_chars": .int(item.phrase.chars.count),
            "mode": .string(mode.rawValue), "strokes": .int(strokes?.count ?? 0), "speed": .number(speed),
            "source": .string(app.photoSource.rawValue), "on_server": .bool(!item.adHoc),
            "text": .string(item.phrase.text), "romanization": .opt(item.phrase.romanization(at: item.charIndex) ?? item.phrase.romanization),
        ])
        introduce(item)
        beginWriting()
    }

    private func resetPacer(speed: Double) {
        let count = mode == .dictation ? 1 : max(1, strokes?.count ?? 1)
        pacer = Pacer(strokeCount: count, now: Date(), speed: speed)
        // Whole-letter tracing (no stroke data) and dictation: wait longer for the pen to settle.
        pacer.settle = (mode == .dictation || !hasStrokeOrder) ? 2.6 : 1.3
        if mode == .dictation { pacer.baseTimeout = 25 } else if !hasStrokeOrder { pacer.baseTimeout = 9 }
        shownStroke = 1
        strokeEpoch += 1
        lastTrigger = nil
    }

    private func introduce(_ item: PracticeItem) {
        if let audio = item.phrase.audio, let url = app.api?.url(audio), item.charIndex == 0 || mode == .dictation {
            Sounds.shared.play(url: url, rate: speed > 1.2 ? 0.8 : 1)
        }
        if mode == .dictation {
            let what = item.phrase.meaning.map { "“\($0)”" } ?? item.phrase.text
            app.say(item.phrase.chars.count > 1
                    ? "From memory: write character \(item.charIndex + 1) of \(what)."
                    : "From memory: write \(what).")
        }
        showStroke(1, trigger: .manual)
    }

    private func beginWriting() {
        ink.reset()
        lastInk = nil
        dictationInkAt = nil
        dictationStartedAt = Date()
        phase = .writing
        if app.photoSource == .phone {
            Task { await app.camera.start() }
            app.camera.simulated.reset(strokes: strokes, glyph: current?.char ?? "")
        }
        loopTask = Task { [weak self] in await self?.captureLoop() }
    }

    // MARK: capture loop (tier 1)

    private func captureLoop() async {
        var nextAt = Date()
        while !Task.isCancelled, running, phase == .writing {
            let wait = nextAt.timeIntervalSinceNow
            if wait > 0 { try? await Task.sleep(for: .seconds(wait)) }
            guard !Task.isCancelled, phase == .writing else { return }
            nextAt = Date().addingTimeInterval(1.0)
            simulatePen()

            let t0 = Date()
            let frame: CGImage?
            if app.photoSource == .glasses {
                do {
                    let (jpeg, timing) = try await app.glasses.takePhoto()
                    frame = Self.decode(jpeg)
                    app.recordLatency(.capture, ms: timing.totalMs)
                    app.report("glasses.frame", ["ms": .int(timing.totalMs), "shutter_ms": .int(timing.shutterMs),
                                                 "list_ms": .int(timing.listMs), "download_ms": .int(timing.downloadMs)])
                } catch {
                    app.report("glasses.photo_failed", ["error": .string(error.localizedDescription)])
                    frame = nil
                }
            } else {
                frame = app.camera.frame()
                app.recordLatency(.capture, ms: Self.ms(since: t0))
            }
            guard let frame, phase == .writing else { continue }
            lastPhoto = frame
            let t1 = Date()
            let r = ink.process(frame)
            let diffMs = Self.ms(since: t1)
            app.recordLatency(.inkDiff, ms: diffMs)
            lastInk = r
            if r.strokeAdded {
                app.recordLatency(.nextStroke, ms: Self.ms(since: t0))
                app.report("ink", ["new_ink": .number(r.newInk), "coverage": .number(r.inkCoverage),
                                   "tier1_ms": .int(diffMs), "pen_to_next_ms": .int(Self.ms(since: t0))])
                inkArrived(frame)
            }
        }
    }

    /// Simulator / no camera: a pretend writer adds the shown stroke ~1.4 s after it appears.
    private func simulatePen() {
        guard app.photoSource == .phone, app.camera.usesSimulatedPage else { return }
        let page = app.camera.simulated
        let target = mode == .dictation ? (strokes?.count ?? 3) : shownStroke
        let delay = mode == .dictation ? 0.9 : 1.4 * pacer.speed
        if page.strokesDrawn < target, Date().timeIntervalSince(strokeShownAt) > delay {
            page.strokesDrawn += 1
            if mode == .dictation { strokeShownAt = Date() }
        }
    }

    private func inkArrived(_ frame: CGImage) {
        if mode == .dictation { dictationInkAt = Date(); return }
        apply(pacer.strokeWritten(.ink))
        if app.useStrokeMatch, let jpeg = PhoneCamera.jpeg(frame, quality: 0.6), let item = current, let api = app.api {
            let strokeIndex = max(0, shownStroke - 2)   // the stroke that was just written (0-based)
            Task { [weak self] in
                let t = Date()
                guard let m = try? await api.strokeMatch(jpeg: jpeg, char: item.char, lang: item.lang, strokeIndex: strokeIndex) else { return }
                self?.app.recordLatency(.strokeMatch, ms: Self.ms(since: t))
                self?.app.report("stroke_match", ["stroke": .int(strokeIndex + 1), "score": .number(m.score), "done": .bool(m.done)])
            }
        }
    }

    private func tick() {
        now = Date()
        guard phase == .writing else { return }
        if mode == .dictation {
            if let at = dictationInkAt, now.timeIntervalSince(at) > 3.2 { finalize(.ink) }
            else if now.timeIntervalSince(dictationStartedAt) > pacer.timeout { finalize(.timeout) }
            return
        }
        apply(pacer.tick(now: now))
    }

    private func apply(_ actions: [Pacer.Action]) {
        for a in actions {
            switch a {
            case .showStroke(let i, _, let trigger): showStroke(i, trigger: trigger)
            case .finalize(let trigger): finalize(trigger)
            }
        }
    }

    private func showStroke(_ i: Int, trigger: Pacer.Trigger) {
        shownStroke = i
        strokeEpoch += 1
        lastTrigger = trigger
        strokeShownAt = Date()
        guard let item = current else { return }
        // `stroke` is 0-based (the glasses page shows stroke + 1); `stroke_number` is for humans.
        app.report("glasses.show", [
            "char": .string(item.char), "stroke": .int(i - 1), "stroke_number": .int(i), "stroke_count": .int(strokes?.count ?? 0),
            "trigger": .string(trigger.rawValue), "phase": .string(mode == .dictation ? "dictation" : "write"),
        ])
        if trigger != .manual { Sounds.shared.effect(.tick) }
    }

    // MARK: voice / buttons

    func voice(_ cmd: VoiceCommand) {
        switch cmd {
        case .next: next()
        case .again: again()
        case .slower: slower()
        case .check: check()
        default: break
        }
    }

    /// Next stroke while writing; next character after a result.
    func next() {
        switch phase {
        case .writing:
            if mode == .dictation { finalize(.voice) } else { apply(pacer.advance(.voice)) }
        case .result, .failed:
            Task { await begin(index: index + 1) }
        default: break
        }
    }

    func again() {
        guard current != nil else { return }
        app.report("again", ["char": .string(current?.char ?? "")])
        if case .writing = phase {
            apply(pacer.again())
            ink.reset()
            app.camera.simulated.strokesDrawn = 0
        } else {
            Task { await restartCurrent() }
        }
    }

    func slower() {
        pacer.slower()
        strokeEpoch += 1          // replay the current stroke at the new speed
        app.report("slower", ["speed": .number(pacer.speed)])
    }

    func check() {
        guard phase == .writing else { return }
        finalize(.voice)
    }

    func skip() { Task { await begin(index: index + 1) } }

    private func restartCurrent() async {
        advanceTask?.cancel()
        let speed = pacer.speed
        resetPacer(speed: speed)
        reactionLine = nil
        app.camera.simulated.reset(strokes: strokes, glyph: current?.char ?? "")
        showStroke(1, trigger: .manual)
        beginWriting()
    }

    // MARK: grading (tier 3)

    private func finalize(_ trigger: Pacer.Trigger) {
        guard phase == .writing, let item = current else { return }
        loopTask?.cancel()
        phase = .checking
        app.report("grade.start", ["char": .string(item.char), "trigger": .string(trigger.rawValue)])
        Task { await grade(item) }
    }

    private func grade(_ item: PracticeItem) async {
        if app.photoSource == .phone, app.camera.usesSimulatedPage {
            app.camera.simulated.strokesDrawn = max(app.camera.simulated.strokesDrawn, strokes?.count ?? 3)
        }
        var jpeg: Data?
        if app.photoSource == .glasses {
            jpeg = try? await app.glasses.takePhoto().0
        }
        if jpeg == nil { jpeg = app.camera.jpeg() ?? lastPhoto.flatMap { PhoneCamera.jpeg($0) } }
        guard let jpeg, let api = app.api else {
            phase = .failed("No photo to check. Is the camera pointed at the page?")
            return
        }
        let t = Date()
        do {
            let r = try await api.grade(jpeg: jpeg, char: item.char, lang: item.lang)
            app.recordLatency(.grade, ms: Self.ms(since: t))
            guard current == item else { return }
            handle(r, item: item)
        } catch {
            app.report("grade.failed", ["error": .string(error.localizedDescription)])
            guard current == item else { return }
            phase = .failed("Couldn't check that one. \(error.localizedDescription)")
            scheduleAdvance(after: 6, retry: false)
        }
    }

    private func handle(_ r: GradeResult, item: PracticeItem) {
        attemptsOnCurrent += 1
        phase = .result(r)
        outcomes.removeAll { $0.item == item }
        outcomes.append(Outcome(item: item, result: r))
        app.progress.record(item.lang, item.char, correct: r.correct, score: r.scoreInt)
        streak = r.correct ? streak + 1 : 0

        // Reaction: a goofy line + sound from content/reactions.json; streaks get their own.
        var key = Reactions.key(correct: r.correct, score: r.scoreInt)
        var line = app.reactions.line(key)
        if r.correct, app.reactions.isStreak(streak), let s = app.reactions.line("streak", n: streak) {
            key = "streak"; line = s
        }
        let milestone = r.correct ? earnMilestone(item) : nil
        newMilestone = milestone
        if milestone != nil { key = "milestone" }
        reactionLine = milestone?.line.shown ?? line ?? r.reaction ?? r.feedback
        let sounds = app.reactions.sounds(key)
        Sounds.shared.reaction(sounds)

        // Spoken: the milestone, or the fun line when right; the one-line fix when not.
        let spoken = milestone?.line.spoken ?? (r.correct ? (line ?? r.reaction ?? r.feedback) : r.feedback)
        app.say(spoken)

        app.report("grade", ["char": .string(item.char), "score": .int(r.scoreInt), "correct": .bool(r.correct),
                             "feedback": .string(r.feedback), "reaction": .opt(r.reaction), "seen": .opt(r.seen),
                             "next_action": .opt(r.next?.action)])
        app.report("reaction", ["key": .string(key), "line": .opt(reactionLine), "spoken": .string(spoken),
                                "sound": .string(sounds.joined(separator: "+")), "streak": .int(streak)])
        if let m = milestone {
            app.report("milestone", ["id": .string(m.id), "shown": .opt(m.line.shown), "spoken": .string(m.line.spoken)])
        }

        if r.correct {
            confettiBurst += 1
            app.report("confetti", ["char": .string(item.char), "score": .int(r.scoreInt)])
            scheduleAdvance(after: milestone == nil ? 2.4 : 3.8, retry: false)
        } else {
            // The tutor agent decides retry vs. move on; without it, retry once (slower), then move on.
            let retry = r.next?.action.map { $0 == "retry" } ?? (attemptsOnCurrent < 2)
            scheduleAdvance(after: 4.5, retry: retry && attemptsOnCurrent < 3)
        }
    }

    /// content/milestones.json: first letter / first word / first mastered per script, plus first name and all six.
    private func earnMilestone(_ item: PracticeItem) -> EarnedMilestone? {
        let lang = item.lang
        app.langsCorrectThisSitting.insert(lang)
        var fired: [String] = []
        func try_(_ id: String, scope: String) {
            if app.progress.earn("\(scope)/\(id)") { fired.append(id) }
        }
        try_("first_letter", scope: lang)
        // A whole item done right in this run?
        let isLastChar = item.charIndex == item.phrase.chars.count - 1
        let runForItem = outcomes.filter { $0.item.lang == lang && $0.item.phrase.id == item.phrase.id }
        if isLastChar, runForItem.count == item.phrase.chars.count, runForItem.allSatisfy({ $0.result?.correct == true }) {
            if isName { try_("first_name", scope: lang) }
            try_("first_word", scope: lang)
            let n = app.progress.completeItem(lang, item.phrase.id)
            if n >= 3 || mode == .dictation { try_("first_mastered", scope: lang) }
        }
        if app.langsCorrectThisSitting.count >= 6 { try_("all_six_languages", scope: "any") }
        // Show the biggest one.
        let rank = ["all_six_languages", "first_mastered", "first_name", "first_word", "first_letter"]
        guard let best = rank.first(where: fired.contains), let line = app.milestones.line(lang, best) else { return nil }
        return EarnedMilestone(id: "\(lang)/\(best)", line: line)
    }

    private func scheduleAdvance(after seconds: Double, retry: Bool) {
        advanceTask?.cancel()
        guard app.autoAdvance || retry else { return }
        let i = index
        advanceTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(seconds))
            guard let self, !Task.isCancelled, self.index == i, self.running else { return }
            if retry {
                self.pacer.slower()
                await self.restartCurrent()
            } else {
                await self.begin(index: i + 1)
            }
        }
    }

    private func finish() {
        loopTask?.cancel()
        phase = .finished
        app.camera.stop()
        let scores = outcomes.compactMap { $0.result?.scoreInt }
        app.report("practice.finished", ["count": .int(outcomes.count),
                                         "avg": .int(scores.isEmpty ? 0 : scores.reduce(0, +) / scores.count)])
    }

    // MARK: helpers

    private static func ms(since d: Date) -> Int { Int(Date().timeIntervalSince(d) * 1000) }

    private static func decode(_ jpeg: Data) -> CGImage? {
        guard let src = CGImageSourceCreateWithData(jpeg as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }
}
