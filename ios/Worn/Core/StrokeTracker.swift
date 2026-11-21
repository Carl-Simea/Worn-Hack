import Foundation

/// Decides when the stroke being written is actually finished, so the next one never appears mid-stroke.
///
/// Fed once per analysed camera frame (from `InkDiff`):
/// - new ink appeared      → still writing,
/// - frame unusable        → a hand is in view or the page moved: not finished, wait,
/// - ink stopped growing for `quietFramesNeeded` usable frames after writing → the pen is up, the stroke is done.
struct StrokeTracker: Equatable, Sendable {
    enum State: Equatable, Sendable { case watching, writing }

    /// Usable frames without new ink (about one second each) before a stroke counts as finished.
    var quietFramesNeeded = 2
    private(set) var state: State = .watching
    private var quiet = 0

    mutating func reset() { state = .watching; quiet = 0 }

    /// Returns true exactly once per stroke, when it is finished.
    mutating func feed(strokeAdded: Bool, unusable: Bool) -> Bool {
        if unusable { quiet = 0; return false }
        if strokeAdded { state = .writing; quiet = 0; return false }
        guard state == .writing else { return false }
        quiet += 1
        guard quiet >= quietFramesNeeded else { return false }
        reset()
        return true
    }
}
