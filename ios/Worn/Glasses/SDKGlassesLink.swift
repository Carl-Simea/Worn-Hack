#if canImport(MLVisionM6SDK)
import Foundation
import MLVisionM6SDK
import UIKit

/// Glasses via MLVisionM6SDK. Only compiled in the glasses build (ios/scripts/make-glasses-build.sh), which keeps
/// MLDemo's own `GlassesSession` / `DiscoveryGate` (the vendor's tested connection logic and SDK-bug workarounds)
/// and replaces the demo's UI with Worn. Every SDK call here is one MLDemo makes.
@MainActor
final class SDKGlassesLink: GlassesLink {
    private let session = GlassesSession.shared
    private var observer: NSObjectProtocol?
    var onChange: (() -> Void)?

    /// File names already on the phone or seen before, so a new photo can be told apart.
    private var knownFiles: Set<String> = []

    func start() {
        // The SDK wants an NSObject delegate at init (MLDemo passes its home view controller).
        let root = UIApplication.shared.connectedScenes.compactMap { ($0 as? UIWindowScene)?.keyWindow?.rootViewController }.first
        session.start(delegate: root ?? UIViewController())
        observer = NotificationCenter.default.addObserver(forName: .glassesDidChange, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.onChange?() }
        }
        knownFiles = Set(Self.localFiles())
        onChange?()
    }

    var status: GlassesStatus {
        switch session.state {
        case .bluetoothOff: return .bluetoothOff
        case .bluetoothUnauthorized: return .bluetoothUnauthorized
        case .searching: return .searching
        case .connecting(let name): return .connecting(name: name)
        case .connected: return .connected(name: session.connectedName ?? "M6 Glasses", battery: session.batteryLevel)
        case .reconnecting(let attempt): return .lost(attempt: attempt, of: session.reconnectLimit)
        case .idle: return .idle(message: session.idleMessage)
        }
    }

    var nearby: [GlassesDevice] {
        session.nearby.map { GlassesDevice(id: $0.id, name: $0.name, signal: $0.signal) }
    }

    var pairedName: String? { session.pairedGlasses?.name }

    func search() { session.startSearching() }
    func stopSearch() { session.stopSearching() }

    func connect(_ device: GlassesDevice) {
        guard let match = session.nearby.first(where: { $0.id == device.id }) else { return }
        session.connect(to: match)
    }

    func connectPaired() { session.connectToPaired() }
    func cancel() { session.cancelConnecting() }
    func disconnect() { session.disconnect() }

    func speak(_ text: String) {
        guard session.isConnected else { return }
        MLVisionM6SDKManager.playTTS(forAssistant: .exit, text: text, modelId: "namibox")
    }

    // MARK: photo round trip

    /// One photo at a time: the camera app and the file list are shared, so overlapping requests would mix files up.
    private var photoInFlight = false

    func takePhoto() async throws -> (Data, PhotoTiming) {
        while photoInFlight { try await Task.sleep(for: .milliseconds(100)) }
        photoInFlight = true
        defer { photoInFlight = false }
        return try await takePhotoNow()
    }

    private func takePhotoNow() async throws -> (Data, PhotoTiming) {
        guard session.isConnected else { throw GlassesError.notConnected }
        if let problem = GlassesSession.fileTransferNetworkProblem() { throw GlassesError.network(problem) }
        var timing = PhotoTiming()
        let t0 = Date()

        // 1. Shutter (same call as MLDemo's "Take Photo").
        let before = Set(session.pendingFiles.map(GlassesSession.fileName(of:))).union(knownFiles)
        MLVisionM6SDKManager.openApp(25, ext: ["action": "com.mlaixr.camera.takephoto", "CaptureBack": true])
        timing.shutterMs = Self.ms(since: t0)

        // 2. Ask for the file list until the new photo shows up.
        let t1 = Date()
        var newFile: [String: Any]?
        for attempt in 0..<14 {
            if attempt > 0 { try await Task.sleep(for: .milliseconds(attempt < 4 ? 350 : 700)) }
            session.requestFiles()
            try await Self.wait(seconds: 1.5) { [session] in session.fileTransfer != .checking }
            newFile = session.pendingFiles.first { file in
                let name = GlassesSession.fileName(of: file)
                return !name.isEmpty && !name.hasPrefix("cover_pic_") && !before.contains(name)
            }
            if newFile != nil { break }
        }
        guard let file = newFile else { throw GlassesError.timeout("waiting for the photo") }
        let name = GlassesSession.fileName(of: file)
        timing.listMs = Self.ms(since: t1)

        // 3. Download it over Wi-Fi.
        let t2 = Date()
        session.downloadPendingFiles()
        try await Self.wait(seconds: 20) { [session] in
            if case .failed = session.fileTransfer { return true }
            return session.syncedFiles.contains { GlassesSession.fileName(of: $0) == name }
        }
        if case .failed(let message) = session.fileTransfer { throw GlassesError.network(message) }
        guard let synced = session.syncedFiles.first(where: { GlassesSession.fileName(of: $0) == name }),
              let data = Self.readFile(synced, name: name) else { throw GlassesError.noFile }
        timing.downloadMs = Self.ms(since: t2)

        // 4. Tidy up so the next photo is easy to spot.
        knownFiles.insert(name)
        session.confirmDownloads()
        session.deleteFromGlasses(fileName: name)
        return (data, timing)
    }

    private static var downloads: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MLMultiMediaDirectory", isDirectory: true)
    }

    private static func localFiles() -> [String] {
        (try? FileManager.default.contentsOfDirectory(atPath: downloads.path)) ?? []
    }

    private static func readFile(_ file: [String: Any], name: String) -> Data? {
        if let path = file["localPath"] as? String, let d = FileManager.default.contents(atPath: path) { return d }
        return FileManager.default.contents(atPath: downloads.appendingPathComponent(name).path)
    }

    private static func ms(since d: Date) -> Int { Int(Date().timeIntervalSince(d) * 1000) }

    /// Poll a main-actor condition (the session posts changes on the main queue).
    private static func wait(seconds: Double, _ done: @MainActor () -> Bool) async throws {
        let end = Date().addingTimeInterval(seconds)
        while !done() {
            if Date() > end { return }
            try await Task.sleep(for: .milliseconds(80))
        }
    }
}
#endif
