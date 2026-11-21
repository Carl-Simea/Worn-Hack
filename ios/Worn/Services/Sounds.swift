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
    private var effectPlayer: AVAudioPlayer?
    private var effectCache: [Effect: Data] = [:]

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

    /// Synthesized fallback sounds, played with AVAudioPlayer from an in-memory WAV.
    /// (No AVAudioEngine here: a second engine next to the voice recognizer's can abort on an audio-server timeout.)
    func effect(_ e: Effect) {
        if effectCache[e] == nil { effectCache[e] = Self.wav(e) }
        guard let data = effectCache[e], let p = try? AVAudioPlayer(data: data) else { return }
        AudioSessionConfig.activate()
        p.volume = e == .tick ? 0.4 : 0.8
        effectPlayer = p
        p.play()
    }

    func effect(named name: String?) {
        guard let name, let e = Effect(rawValue: name) else { return }
        effect(e)
    }

    /// Tiny synthesizer: sequences of (frequency start, frequency end, seconds) → 16-bit mono WAV.
    private static func wav(_ e: Effect) -> Data {
        let notes: [(Double, Double, Double)]
        switch e {
        case .chime: notes = [(784, 784, 0.09), (1047, 1047, 0.18)]
        case .tada: notes = [(523, 523, 0.08), (659, 659, 0.08), (784, 784, 0.08), (1047, 1047, 0.32)]
        case .pop: notes = [(600, 1400, 0.07)]
        case .boing: notes = [(420, 180, 0.32)]
        case .tick: notes = [(2000, 2000, 0.02)]
        }
        let rate = 44_100
        var samples: [Int16] = []
        var phase = 0.0
        for (f0, f1, dur) in notes {
            let n = Int(dur * Double(rate))
            for k in 0..<n {
                let t = Double(k) / Double(n)
                phase += 2 * .pi * (f0 + (f1 - f0) * t) / Double(rate)
                let env = min(1, t * 30) * pow(1 - t, 2)
                let wobble = e == .boing ? (1 + 0.3 * sin(t * 40)) : 1
                samples.append(Int16(max(-1, min(1, sin(phase) * env * 0.5 * wobble)) * 32_000))
            }
        }
        var d = Data()
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { d.append(contentsOf: $0) } }
        let bytes = UInt32(samples.count * 2)
        d.append(contentsOf: Array("RIFF".utf8)); u32(36 + bytes); d.append(contentsOf: Array("WAVEfmt ".utf8))
        u32(16); u16(1); u16(1); u32(UInt32(rate)); u32(UInt32(rate * 2)); u16(2); u16(16)
        d.append(contentsOf: Array("data".utf8)); u32(bytes)
        samples.withUnsafeBytes { d.append(contentsOf: $0) }
        return d
    }
}
