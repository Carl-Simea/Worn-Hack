import AVFoundation
import Foundation

/// Phone-side audio: pronunciation clips, synthesized reaction sounds, and spoken lines.
@MainActor
final class Sounds {
    static let shared = Sounds()

    private var player: AVPlayer?
    private var sfxPlayer: AVAudioPlayer?
    private var sfxCache: [String: Data] = [:]
    private var sfxTask: Task<Void, Never>?
    /// Set by the app once the server is known; sound effects come from content/sfx/NAME.wav.
    var api: API?
    private let synth = AVSpeechSynthesizer()
    private let engine = AVAudioEngine()
    private let node = AVAudioPlayerNode()
    private var engineReady = false

    /// Pronunciation audio from the backend (content/audio/...). `rate` < 1 plays slower.
    func play(url: URL, rate: Float = 1) {
        AudioSessionConfig.activate()
        let item = AVPlayerItem(url: url)
        item.audioTimePitchAlgorithm = .timeDomain   // keeps pitch natural when slowed
        let p = AVPlayer(playerItem: item)
        player = p
        p.playImmediately(atRate: rate)
    }

    func say(_ text: String, language: String = "en-US", rate: Float = 0.48) {
        AudioSessionConfig.activate()
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: language)
        u.rate = rate
        synth.stopSpeaking(at: .immediate)
        synth.speak(u)
    }

    /// Download the team's sound effects once so reactions play instantly.
    func preload(_ names: [String]) {
        guard let api else { return }
        for n in names where sfxCache[n] == nil {
            Task { if let d = try? await api.staticFile("sfx/\(n).wav") { sfxCache[n] = d } }
        }
    }

    /// Play reaction sounds in order ("drumroll" then "cheer"). Falls back to the built-in synth.
    func reaction(_ names: [String]) {
        sfxTask?.cancel()
        sfxTask = Task {
            for n in names {
                guard !Task.isCancelled else { return }
                let seconds = await playSFX(n)
                try? await Task.sleep(for: .seconds(max(0.15, seconds - 0.1)))
            }
        }
    }

    private func playSFX(_ name: String) async -> Double {
        if sfxCache[name] == nil, let api, let d = try? await api.staticFile("sfx/\(name).wav") { sfxCache[name] = d }
        if let d = sfxCache[name], let p = try? AVAudioPlayer(data: d) {
            AudioSessionConfig.activate()
            sfxPlayer = p
            p.volume = 0.9
            p.play()
            return p.duration
        }
        let fallback: Effect
        switch name {
        case "ding", "kiss", "sparkle": fallback = .chime
        case "tada", "cheer", "drumroll": fallback = .tada
        case "boing", "slide": fallback = .boing
        case "buzzer": fallback = .boing
        default: fallback = .pop
        }
        effect(fallback)
        return 0.4
    }

    enum Effect: String { case chime, tada, pop, boing, tick }

    func effect(_ e: Effect) {
        guard let buffer = Self.render(e) else { return }
        if !engineReady {
            engine.attach(node)
            engine.connect(node, to: engine.mainMixerNode, format: buffer.format)
            engineReady = true
        }
        AudioSessionConfig.activate()
        if !engine.isRunning { try? engine.start() }
        node.stop()
        node.scheduleBuffer(buffer, at: nil)
        node.play()
    }

    func effect(named name: String?) {
        guard let name, let e = Effect(rawValue: name) else { return }
        effect(e)
    }

    /// Tiny synthesizer: sequences of (frequency start, frequency end, seconds).
    private static func render(_ e: Effect) -> AVAudioPCMBuffer? {
        let notes: [(Double, Double, Double)]
        switch e {
        case .chime: notes = [(784, 784, 0.09), (1047, 1047, 0.18)]
        case .tada: notes = [(523, 523, 0.08), (659, 659, 0.08), (784, 784, 0.08), (1047, 1047, 0.32)]
        case .pop: notes = [(600, 1400, 0.07)]
        case .boing: notes = [(420, 180, 0.32)]
        case .tick: notes = [(2000, 2000, 0.02)]
        }
        let rate = 44_100.0
        let frames = AVAudioFrameCount(notes.reduce(0) { $0 + $1.2 } * rate)
        guard let fmt = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1),
              let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: frames),
              let ch = buf.floatChannelData?[0] else { return nil }
        var i = 0
        var phase = 0.0
        for (f0, f1, dur) in notes {
            let n = Int(dur * rate)
            for k in 0..<n {
                let t = Double(k) / Double(n)
                let f = f0 + (f1 - f0) * t
                phase += 2 * .pi * f / rate
                let env = min(1, t * 30) * pow(1 - t, 2)          // fast attack, smooth decay
                let wobble = e == .boing ? (1 + 0.3 * sin(t * 40)) : 1
                ch[i] = Float(sin(phase) * env * 0.35 * wobble)
                i += 1
            }
        }
        buf.frameLength = AVAudioFrameCount(i)
        return buf
    }
}
