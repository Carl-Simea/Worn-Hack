import SwiftUI

/// The voice agent, always in reach: one big round button. Tap = listening on/off.
/// Accent + moving waveform = listening; grey + slashed mic = off.
struct VoiceButton: View {
    @Environment(AppModel.self) private var app
    var size: CGFloat = 60

    var body: some View {
        let on = app.voice.state == .listening
        let paused = app.voice.state == .paused
        Button {
            app.voiceEnabled.toggle()
        } label: {
            ZStack {
                Circle().fill(on || paused ? Theme.accent : Theme.card)
                Circle().strokeBorder(on || paused ? .clear : Theme.hairline, lineWidth: 1)
                Image(systemName: on || paused ? "waveform" : "mic.slash.fill")
                    .font(.system(size: size * 0.38, weight: .semibold))
                    .symbolEffect(.variableColor.iterative.reversing, isActive: on)
                    .foregroundStyle(on || paused ? .white : Theme.inkSoft)
            }
            .frame(width: size, height: size)
            .shadow(color: .black.opacity(on ? 0.16 : 0.08), radius: 10, y: 4)
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel(on ? "Voice on. Tap to turn off" : "Voice off. Tap to turn on")
    }
}

/// The bar under every screen: voice in the centre, feedback on the right (left side kept empty so the mic is centred).
struct AppBar: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        HStack {
            Color.clear.frame(width: 48, height: 48)
            Spacer()
            VStack(spacing: 4) {
                VoiceButton(size: 60)
                if let hint {
                    Text(hint).font(Theme.sans(14, weight: .medium)).foregroundStyle(Theme.inkSoft).lineLimit(1)
                }
            }
            Spacer()
            FeedbackButton()
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)
        .padding(.bottom, 4)
        .background(Theme.paper.opacity(0.94))
    }

    private var hint: String? {
        switch app.voice.state {
        case .listening: return app.voice.lastHeard.isEmpty ? "Say “next”" : "“\(app.voice.lastHeard.split(separator: " ").suffix(3).joined(separator: " "))”"
        case .unauthorized: return "Allow microphone in Settings"
        default: return nil
        }
    }
}

/// Flag button: opens the feedback window with a screenshot of what's on screen right now.
struct FeedbackButton: View {
    @Environment(AppModel.self) private var app
    var size: CGFloat = 48

    var body: some View {
        Button { app.startFeedback() } label: {
            Image(systemName: "flag.fill")
                .font(.system(size: size * 0.38, weight: .semibold))
                .foregroundStyle(Theme.ink)
                .frame(width: size, height: size)
                .background(Theme.card, in: Circle())
                .overlay(Circle().strokeBorder(Theme.hairline))
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel("Send feedback")
    }
}
