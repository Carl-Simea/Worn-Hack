import Foundation

/// What the app needs from the M6 glasses. The SDK can't draw on the glasses display (no such API in
/// MLVisionM6SDK); the display shows the backend's /glasses page, which follows /session and /event.
enum GlassesStatus: Equatable, Sendable {
    /// This build doesn't include MLVisionM6SDK (simulator / standalone project). Demo Mode only.
    case noSDK
    case bluetoothOff
    case bluetoothUnauthorized
    case idle(message: String?)
    case searching
    case connecting(name: String)
    case connected(name: String, battery: Int?)
    case lost(attempt: Int, of: Int)

    var isConnected: Bool { if case .connected = self { return true } else { return false } }

    var title: String {
        switch self {
        case .noSDK: return "Glasses need the SDK build"
        case .bluetoothOff: return "Bluetooth is off"
        case .bluetoothUnauthorized: return "Bluetooth not allowed"
        case .idle: return "Not connected"
        case .searching: return "Searching…"
        case .connecting(let n): return "Connecting to \(n)…"
        case .connected(let n, _): return n
        case .lost: return "Connection lost"
        }
    }
}

struct GlassesDevice: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let signal: String
}

/// Timing for one glasses photo, for the debug overlay.
struct PhotoTiming: Equatable, Sendable {
    var shutterMs = 0
    var listMs = 0
    var downloadMs = 0
    var totalMs: Int { shutterMs + listMs + downloadMs }
}

enum GlassesError: LocalizedError {
    case notConnected, timeout(String), network(String), noFile

    var errorDescription: String? {
        switch self {
        case .notConnected: return "Glasses aren't connected."
        case .timeout(let step): return "The glasses took too long (\(step))."
        case .network(let m): return m
        case .noFile: return "The photo didn't arrive from the glasses."
        }
    }
}

@MainActor
protocol GlassesLink: AnyObject {
    var status: GlassesStatus { get }
    var nearby: [GlassesDevice] { get }
    var pairedName: String? { get }
    /// Called on the main actor whenever status / nearby change.
    var onChange: (() -> Void)? { get set }

    func start()
    func search()
    func stopSearch()
    func connect(_ device: GlassesDevice)
    func connectPaired()
    func cancel()
    func disconnect()

    /// Speak through the glasses' speaker (English lines; pronunciation clips play on the phone).
    func speak(_ text: String)
    /// Take a photo with the glasses camera and bring it to the phone (JPEG).
    func takePhoto() async throws -> (Data, PhotoTiming)
}

/// Used when the SDK isn't linked: always "noSDK"; photos come from the phone instead.
@MainActor
final class NoGlassesLink: GlassesLink {
    let status: GlassesStatus = .noSDK
    let nearby: [GlassesDevice] = []
    let pairedName: String? = nil
    var onChange: (() -> Void)?
    func start() {}
    func search() {}
    func stopSearch() {}
    func connect(_ device: GlassesDevice) {}
    func connectPaired() {}
    func cancel() {}
    func disconnect() {}
    func speak(_ text: String) {}
    func takePhoto() async throws -> (Data, PhotoTiming) { throw GlassesError.notConnected }
}

enum GlassesLinkFactory {
    @MainActor static func make() -> GlassesLink {
        #if canImport(MLVisionM6SDK)
        return SDKGlassesLink()
        #else
        return NoGlassesLink()
        #endif
    }
}
