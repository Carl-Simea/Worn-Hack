import AVFoundation
import Foundation
import Observation
import Speech

/// Always-on, on-device command listener (Apple Speech). Fires each command once per utterance.
@MainActor
@Observable
final class VoiceListener {
    enum State: Equatable { case off, unauthorized, unavailable, listening, paused }

    private(set) var state: State = .off { didSet { if state != oldValue { onStateChange?(state) } } }
    var onStateChange: ((State) -> Void)?
    private(set) var lastHeard = ""
    private(set) var lastCommand: VoiceCommand?
    var onCommand: ((VoiceCommand) -> Void)?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var firedForUtterance: Set<String> = []
    private var restartWork: Task<Void, Never>?
    /// Back off when the recognizer keeps failing (e.g. on-device model missing) instead of spinning.
    private var failures = 0
    private var startedAt = Date()

    var isOnDevice: Bool { recognizer?.supportsOnDeviceRecognition ?? false }

    func start() async {
        guard state != .listening else { return }
        let speech = await withCheckedContinuation { (c: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0) }
        }
        guard speech == .authorized else { state = .unauthorized; return }
        let mic = await AVAudioApplication.requestRecordPermission()
        guard mic else { state = .unauthorized; return }
        guard let recognizer, recognizer.isAvailable else { state = .unavailable; return }
        do {
            try begin(recognizer)
            state = .listening
        } catch {
            state = .unavailable
        }
    }

    func stop() {
        restartWork?.cancel()
        teardown()
        state = .off
    }

    /// Pause while the app itself is talking, so it doesn't hear its own prompts.
    func pause() { if state == .listening { teardown(); state = .paused } }

    func resume() {
        guard state == .paused, let recognizer else { return }
        do { try begin(recognizer); state = .listening } catch { state = .unavailable }
    }

    private func begin(_ recognizer: SFSpeechRecognizer) throws {
        teardown()
        AudioSessionConfig.activate()
        let req = SFSpeechAudioBufferRecognitionRequest()
        req.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }
        req.taskHint = .confirmation
        req.contextualStrings = ["next", "back", "again", "slower", "check", "switch to", "help me write",
                                 "Mandarin", "Hindi", "Arabic", "Russian", "Hebrew", "Greek"]
        request = req

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { throw NSError(domain: "Worn.voice", code: 1) }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak req] buffer, _ in
            req?.append(buffer)
        }
        engine.prepare()
        try engine.start()

        firedForUtterance = []
        startedAt = Date()
        task = recognizer.recognitionTask(with: req) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let isFinal = result?.isFinal ?? false
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let text { self.heard(text); self.failures = 0 }
                if error != nil, Date().timeIntervalSince(self.startedAt) < 2 { self.failures += 1 }
                if isFinal || error != nil {
                    self.scheduleRestart(after: min(5, 0.2 * pow(2, Double(min(self.failures, 5)))))
                }
            }
        }
    }

    private func heard(_ text: String) {
        lastHeard = text
        guard let cmd = VoiceCommandParser.parse(text) else { return }
        // Fire once per distinct command per utterance (partials repeat the same words).
        let key = "\(cmd)"
        guard !firedForUtterance.contains(key) else { return }
        firedForUtterance.insert(key)
        lastCommand = cmd
        onCommand?(cmd)
        // Start a fresh utterance so "next … next" works as two commands.
        scheduleRestart(after: 0.35)
    }

    private func scheduleRestart(after delay: Double = 0.2) {
        guard state == .listening else { return }
        restartWork?.cancel()
        restartWork = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self, !Task.isCancelled, self.state == .listening, let r = self.recognizer else { return }
            do { try self.begin(r) } catch { self.state = .unavailable }
        }
    }

    private func teardown() {
        task?.cancel(); task = nil
        request?.endAudio(); request = nil
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
    }
}

enum AudioSessionConfig {
    /// Record (voice commands) and play (pronunciation, reactions) at the same time, through the speaker.
    static func activate() {
        #if os(iOS)
        let s = AVAudioSession.sharedInstance()
        try? s.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .duckOthers])
        try? s.setActive(true)
        #endif
    }
}
