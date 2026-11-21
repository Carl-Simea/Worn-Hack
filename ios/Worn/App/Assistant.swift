import Foundation
import Observation

struct VoiceReply: Decodable {
    let heard: String?
    let intent: String?
    let say: String?
}

struct ChatMessage: Identifiable, Equatable {
    enum Role { case you, scribi }
    let id = UUID()
    let role: Role
    let text: String
}

/// The voice assistant as a conversation: what you said (transcribed live), what Scribi answered, spoken aloud.
@MainActor
@Observable
final class Assistant {
    enum Phase: Equatable { case idle, listening, thinking, speaking }

    private(set) var messages: [ChatMessage] = []
    private(set) var phase: Phase = .idle
    var isOpen = false
    /// Mic muted by the user inside the chat.
    var muted = false
    private unowned let app: AppModel

    init(app: AppModel) { self.app = app }

    /// Words as they're being heard, before the sentence is complete.
    var live: String { app.voice.partial }

    func open() {
        isOpen = true
        if messages.isEmpty {
            messages.append(ChatMessage(role: .scribi, text: "Hi! Ask me anything about the letter you're writing, or tell me what to do."))
        }
        app.voice.onUtterance = { [weak self] text in self?.heard(text) }
        app.voice.conversation = true
        Task {
            if app.voice.state == .off || app.voice.state == .paused { await startListening() }
            else { phase = .listening }
        }
    }

    func close() {
        isOpen = false
        Sounds.shared.stopSpeaking()
        app.voice.conversation = false
        app.voice.onUtterance = nil
        phase = .idle
        if !app.voiceEnabled { app.voice.stop() }
    }

    func toggleMute() {
        muted.toggle()
        if muted { app.voice.pause(); phase = .idle } else { app.voice.resume(); phase = .listening }
    }

    private func startListening() async {
        await app.voice.start()
        phase = app.voice.state == .listening ? .listening : .idle
    }

    /// A sentence from the microphone or the text field.
    func heard(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, phase != .thinking else { return }
        Sounds.shared.stopSpeaking()
        messages.append(ChatMessage(role: .you, text: t))
        app.report("assistant.heard", ["text": .string(t)])
        phase = .thinking
        app.voice.pause()
        Task { await respond(to: t) }
    }

    private func respond(to t: String) async {
        // Plain commands (next, back, check, switch to Hebrew …) act on the phone straight away.
        if let cmd = VoiceCommandParser.parse(t) {
            app.handle(cmd)
            reply(Self.confirmation(for: cmd))
            return
        }
        guard let api = app.api else { reply("I can't reach my brain right now. Check the connection."); return }
        do {
            let r = try await api.ask(t)
            let say = r.say?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            reply(say.isEmpty ? "Hmm, I didn't catch that. Try again?" : say)
        } catch {
            app.report("assistant.failed", ["error": .string(error.localizedDescription)])
            reply("Sorry, I couldn't reach my brain. Try again in a moment.")
        }
    }

    private func reply(_ text: String) {
        messages.append(ChatMessage(role: .scribi, text: text))
        app.report("assistant.reply", ["text": .string(text)])
        phase = .speaking
        Sounds.shared.say(text) { [weak self] in
            guard let self else { return }
            if self.isOpen, !self.muted { self.app.voice.resume() }
            self.phase = self.isOpen && !self.muted ? .listening : .idle
        }
    }

    private static func confirmation(for cmd: VoiceCommand) -> String {
        switch cmd {
        case .next: return "Next stroke."
        case .back: return "Going back one."
        case .again: return "Here it is again."
        case .slower: return "Slower, got it."
        case .check: return "Okay, checking."
        case .switchTo: return "Switching."
        case .helpMeWrite: return "Sure, let's write that."
        }
    }
}
