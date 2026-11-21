import Foundation

/// Seen → Practiced → Mastered, per character per language. Stored on-device (UserDefaults, JSON).
struct CharProgress: Codable, Equatable, Sendable {
    var seen = 0
    var attempts = 0
    var correct = 0
    var best = 0
    var lastScore: Int?
    var lastCorrect: Bool?
    var misses = 0          // consecutive incorrect attempts
    var lastSeen: Date?

    enum Level: Int, Comparable, Sendable {
        case new, seen, practiced, mastered
        static func < (a: Level, b: Level) -> Bool { a.rawValue < b.rawValue }
        var label: String { ["New", "Seen", "Practiced", "Mastered"][rawValue] }
    }

    var level: Level {
        if correct >= 2 && best >= 85 { return .mastered }
        if attempts > 0 { return .practiced }
        if seen > 0 { return .seen }
        return .new
    }

    /// Adaptive animation speed: slower after misses, a little quicker once mastered.
    var animationSpeed: Double {
        if misses >= 2 { return 1.8 }
        if misses == 1 || lastCorrect == false { return 1.4 }
        if level == .mastered { return 0.8 }
        return 1
    }
}

struct ProgressBook: Codable, Equatable, Sendable {
    var chars: [String: CharProgress] = [:]     // "lang/char"
    var practiceDays: Set<String> = []          // "yyyy-MM-dd"
    var earnedMilestones: Set<String> = []
    var perfectScores = 0

    static func key(_ lang: String, _ char: String) -> String { "\(lang)/\(char)" }

    func progress(_ lang: String, _ char: String) -> CharProgress { chars[Self.key(lang, char)] ?? CharProgress() }

    mutating func markSeen(_ lang: String, _ char: String, now: Date = Date()) {
        chars[Self.key(lang, char), default: CharProgress()].seen += 1
        chars[Self.key(lang, char)]?.lastSeen = now
    }

    mutating func record(_ lang: String, _ char: String, correct: Bool, score: Int, now: Date = Date()) {
        var p = progress(lang, char)
        p.attempts += 1
        p.lastScore = score
        p.lastCorrect = correct
        p.best = max(p.best, score)
        p.lastSeen = now
        if correct { p.correct += 1; p.misses = 0 } else { p.misses += 1 }
        chars[Self.key(lang, char)] = p
        practiceDays.insert(Self.day(now))
        if score >= 100 { perfectScores += 1 }
    }

    /// Ring value for a language: mastered = 1, practiced = 0.5, seen = 0.15, over the lesson's distinct chars.
    func ring(for lesson: Lesson) -> Double {
        let unique = Array(Set(lesson.phrases.flatMap(\.chars)))
        guard !unique.isEmpty else { return 0 }
        let sum = unique.reduce(0.0) { acc, c in
            switch progress(lesson.lang, c).level {
            case .mastered: return acc + 1
            case .practiced: return acc + 0.5
            case .seen: return acc + 0.15
            case .new: return acc
            }
        }
        return sum / Double(unique.count)
    }

    func count(_ level: CharProgress.Level, lang: String? = nil) -> Int {
        chars.filter { (k, v) in v.level == level && (lang == nil || k.hasPrefix(lang! + "/")) }.count
    }

    func streak(now: Date = Date()) -> Int {
        var n = 0
        var day = now
        let cal = Calendar.current
        // Today counts if practiced; otherwise the streak can still be alive from yesterday.
        if !practiceDays.contains(Self.day(day)) { day = cal.date(byAdding: .day, value: -1, to: day) ?? day }
        while practiceDays.contains(Self.day(day)) {
            n += 1
            day = cal.date(byAdding: .day, value: -1, to: day) ?? day
        }
        return n
    }

    func practicedToday(now: Date = Date()) -> Int {
        let cal = Calendar.current
        return chars.values.filter { $0.attempts > 0 && $0.lastSeen.map { cal.isDate($0, inSameDayAs: now) } == true }.count
    }

    /// Newly earned milestones after a grade.
    mutating func checkMilestones(_ all: Milestones, lessons: [Lesson], lastScore: Int, now: Date = Date()) -> [Milestones.Milestone] {
        var new: [Milestones.Milestone] = []
        let mastered = count(.mastered)
        let anyCorrect = chars.values.contains { $0.correct > 0 }
        for m in all.milestones where !earnedMilestones.contains(m.id) {
            let hit: Bool
            switch m.kind {
            case "first_correct": hit = anyCorrect
            case "chars_mastered": hit = mastered >= (m.count ?? 1)
            case "streak_days": hit = streak(now: now) >= (m.count ?? 1)
            case "perfect_score": hit = lastScore >= (m.count ?? 100)
            case "lang_complete":
                hit = lessons.contains { l in
                    let u = Set(l.phrases.flatMap(\.chars))
                    return !u.isEmpty && u.allSatisfy { progress(l.lang, $0).level >= .practiced }
                }
            default: hit = false
            }
            if hit { earnedMilestones.insert(m.id); new.append(m) }
        }
        return new
    }

    static func day(_ d: Date) -> String {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }

    // MARK: persistence

    static func load() -> ProgressBook {
        guard let d = UserDefaults.standard.data(forKey: "progress.v1"),
              let b = try? JSONDecoder().decode(ProgressBook.self, from: d) else { return ProgressBook() }
        return b
    }

    func save() {
        if let d = try? JSONEncoder().encode(self) { UserDefaults.standard.set(d, forKey: "progress.v1") }
    }
}
