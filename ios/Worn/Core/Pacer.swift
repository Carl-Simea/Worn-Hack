import Foundation

/// Auto-pacing for one character. Pure state machine: feed it events, it returns what to do.
///
/// The glasses (and phone) show stroke `shown` (1-based). It advances to the next stroke on whichever comes first:
/// - tier 1: new ink detected on-device (`InkDiff`), optionally confirmed by `/stroke-match`,
/// - voice: the learner says "next",
/// - timeout: `timeout` seconds without progress (never gets stuck).
/// After the last stroke has been shown and written, it asks for the final photo → `/grade`.
struct Pacer: Equatable, Sendable {
    enum Trigger: String, Sendable { case ink, voice, timeout, strokeMatch = "stroke_match", manual }

    enum Action: Equatable, Sendable {
        case showStroke(index: Int, of: Int, trigger: Trigger)
        case finalize(trigger: Trigger)
    }

    let strokeCount: Int
    /// Seconds without progress before auto-advancing. Scaled by the speed multiplier.
    var baseTimeout: TimeInterval = 4
    /// 1 = normal, >1 slower (voice "slower", or adaptive after misses).
    var speed: Double = 1
    /// Seconds to wait after the last stroke before taking the final photo (lets the pen lift).
    var settle: TimeInterval = 1.2

    private(set) var shown = 1
    private(set) var lastProgress: Date
    private(set) var finalizing = false
    private var lastStrokeWrittenAt: Date?

    init(strokeCount: Int, now: Date = Date(), speed: Double = 1) {
        self.strokeCount = max(1, strokeCount)
        self.speed = speed
        lastProgress = now
    }

    var timeout: TimeInterval { baseTimeout * speed }
    var isOnLastStroke: Bool { shown >= strokeCount }

    /// Fraction of the timeout used (drives the little countdown ring in the UI).
    func timeoutProgress(now: Date) -> Double {
        min(1, max(0, now.timeIntervalSince(lastProgress) / timeout))
    }

    mutating func restart(now: Date = Date()) {
        shown = 1; finalizing = false; lastStrokeWrittenAt = nil; lastProgress = now
    }

    /// New ink seen (tier 1) or a stroke-match says the current stroke is done.
    mutating func strokeWritten(_ trigger: Trigger, now: Date = Date()) -> [Action] {
        guard !finalizing else { return [] }
        lastProgress = now
        if isOnLastStroke {
            lastStrokeWrittenAt = now   // finalize after `settle` (see tick)
            return []
        }
        shown += 1
        return [.showStroke(index: shown, of: strokeCount, trigger: trigger)]
    }

    /// Voice "next" / "check" or a button: skip ahead without waiting for ink.
    mutating func advance(_ trigger: Trigger, now: Date = Date()) -> [Action] {
        guard !finalizing else { return [] }
        lastProgress = now
        if isOnLastStroke {
            finalizing = true
            return [.finalize(trigger: trigger)]
        }
        shown += 1
        return [.showStroke(index: shown, of: strokeCount, trigger: trigger)]
    }

    /// Call about every 0.25 s.
    mutating func tick(now: Date = Date()) -> [Action] {
        guard !finalizing else { return [] }
        if let written = lastStrokeWrittenAt, now.timeIntervalSince(written) >= settle {
            finalizing = true
            return [.finalize(trigger: .ink)]
        }
        if now.timeIntervalSince(lastProgress) >= timeout {
            return advance(.timeout, now: now)
        }
        return []
    }

    /// "again": show the first stroke again.
    mutating func again(now: Date = Date()) -> [Action] {
        restart(now: now)
        return [.showStroke(index: 1, of: strokeCount, trigger: .manual)]
    }

    mutating func slower(now: Date = Date()) {
        speed = min(3, speed * 1.5)
        lastProgress = now
    }
}
