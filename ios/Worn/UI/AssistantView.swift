import SwiftUI

/// Chat window for the voice assistant: your words (live), Scribi's answers, spoken aloud.
struct AssistantView: View {
    @Environment(AppModel.self) private var app
    @State private var typed = ""
    @FocusState private var typing: Bool

    var body: some View {
        let a = app.assistant
        VStack(spacing: 0) {
            header(a)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(a.messages) { m in Bubble(message: m).id(m.id) }
                        if !a.live.isEmpty {
                            Bubble(message: ChatMessage(role: .you, text: a.live), faded: true).id("live")
                        }
                        if a.phase == .thinking {
                            HStack { ProgressView().controlSize(.small); Text("Thinking…").font(Theme.sans(15)).foregroundStyle(Theme.inkSoft); Spacer() }
                                .padding(.horizontal, 20).id("thinking")
                        }
                    }
                    .padding(.vertical, 12)
                }
                .onChange(of: a.messages.count) { _, _ in scroll(proxy, a) }
                .onChange(of: a.live) { _, _ in scroll(proxy, a) }
                .onChange(of: a.phase) { _, _ in scroll(proxy, a) }
            }
            controls(a)
        }
        .background(Theme.paper.ignoresSafeArea())
        .presentationDetents([.large])
    }

    private func scroll(_ p: ScrollViewProxy, _ a: Assistant) {
        withAnimation(.easeOut(duration: 0.2)) {
            if !a.live.isEmpty { p.scrollTo("live", anchor: .bottom) }
            else if a.phase == .thinking { p.scrollTo("thinking", anchor: .bottom) }
            else if let last = a.messages.last { p.scrollTo(last.id, anchor: .bottom) }
        }
    }

    private func header(_ a: Assistant) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Scribi").font(Theme.sans(22, weight: .bold)).foregroundStyle(Theme.ink)
                Text(status(a)).font(Theme.sans(14, weight: .medium)).foregroundStyle(a.phase == .listening ? Theme.accent : Theme.inkSoft)
            }
            Spacer()
            Button { a.close() } label: {
                Image(systemName: "xmark").font(.system(size: 16, weight: .bold)).foregroundStyle(Theme.ink)
                    .frame(width: 40, height: 40).background(Theme.card, in: Circle()).overlay(Circle().strokeBorder(Theme.hairline))
            }
        }
        .padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 8)
    }

    private func status(_ a: Assistant) -> String {
        if a.muted { return "Mic is off" }
        switch app.voice.state {
        case .unauthorized: return "Allow microphone and speech in Settings"
        case .unavailable: return "Speech recognition isn't available"
        default: break
        }
        switch a.phase {
        case .listening: return "Listening… just talk"
        case .thinking: return "Thinking…"
        case .speaking: return "Speaking…"
        case .idle: return "Tap the mic to talk"
        }
    }

    private func controls(_ a: Assistant) -> some View {
        HStack(spacing: 12) {
            TextField("Or type here", text: $typed)
                .focused($typing)
                .submitLabel(.send)
                .onSubmit(send)
                .font(Theme.sans(17))
                .padding(.horizontal, 16).frame(height: 52)
                .background(Theme.card, in: Capsule())
                .overlay(Capsule().strokeBorder(Theme.hairline))
            Button {
                if typed.isEmpty { a.toggleMute() } else { send() }
            } label: {
                let on = a.phase == .listening || a.phase == .speaking
                Image(systemName: typed.isEmpty ? (a.muted ? "mic.slash.fill" : "waveform") : "arrow.up")
                    .font(.system(size: 22, weight: .semibold))
                    .symbolEffect(.variableColor.iterative.reversing, isActive: a.phase == .listening && typed.isEmpty)
                    .foregroundStyle(on || !typed.isEmpty ? .white : Theme.inkSoft)
                    .frame(width: 56, height: 56)
                    .background(on || !typed.isEmpty ? Theme.accent : Theme.card, in: Circle())
                    .overlay(Circle().strokeBorder(on || !typed.isEmpty ? .clear : Theme.hairline))
            }
            .buttonStyle(PressableStyle())
            .accessibilityLabel(a.muted ? "Turn microphone on" : "Microphone")
        }
        .padding(.horizontal, 20).padding(.vertical, 10)
        .background(Theme.paper)
    }

    private func send() {
        let t = typed; typed = ""
        app.assistant.heard(t)
    }
}

private struct Bubble: View {
    let message: ChatMessage
    var faded = false

    var body: some View {
        let you = message.role == .you
        HStack {
            if you { Spacer(minLength: 48) }
            Text(message.text)
                .font(Theme.sans(18))
                .foregroundStyle(you ? .white : Theme.ink)
                .padding(.horizontal, 16).padding(.vertical, 12)
                .background(you ? Theme.accent : Theme.card, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).strokeBorder(you ? .clear : Theme.hairline))
                .opacity(faded ? 0.65 : 1)
            if !you { Spacer(minLength: 48) }
        }
        .padding(.horizontal, 20)
    }
}

/// Opens the chat window. Sits in the bar under every screen.
struct AssistantButton: View {
    @Environment(AppModel.self) private var app
    var size: CGFloat = 48

    var body: some View {
        Button { app.assistant.open() } label: {
            Image(systemName: "bubble.left.and.text.bubble.right.fill")
                .font(.system(size: size * 0.38, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .frame(width: size, height: size)
                .background(Theme.card, in: Circle())
                .overlay(Circle().strokeBorder(Theme.hairline))
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel("Talk with Scribi")
    }
}
