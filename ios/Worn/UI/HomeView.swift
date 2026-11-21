import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var app
    @State private var showSettings = false

    private var lessons: [Lesson] {
        app.lessons.sorted { (ScriptInfo.order.firstIndex(of: $0.lang) ?? 99) < (ScriptInfo.order.firstIndex(of: $1.lang) ?? 99) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                if !app.hasServer || (app.lessons.isEmpty && app.link != .unknown) {
                    ServerCard(showSettings: $showSettings)
                } else if app.lessons.isEmpty {
                    LoadingCards()
                } else {
                    Eyebrow(text: "Choose a script")
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)], spacing: 14) {
                        ForEach(lessons) { l in
                            NavigationLink(value: Route.lesson(l.lang)) { LanguageCard(lesson: l) }
                                .buttonStyle(PressableStyle())
                        }
                    }
                    Eyebrow(text: "Make it yours").padding(.top, 6)
                    HStack(spacing: 14) {
                        NavigationLink(value: Route.name) {
                            FeatureCard(symbol: "signature", title: "Write your name", detail: "In every script")
                        }.buttonStyle(PressableStyle())
                        NavigationLink(value: Route.daily) {
                            FeatureCard(symbol: "sparkles", title: "Daily 5", detail: "Five picked for today")
                        }.buttonStyle(PressableStyle())
                    }
                    NavigationLink(value: Route.compose) {
                        HStack(spacing: 14) {
                            Image(systemName: "text.bubble").font(.system(size: 22)).foregroundStyle(Theme.accent)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Help me write…").font(Theme.display(19))
                            }
                            Spacer()
                            Image(systemName: "chevron.right").foregroundStyle(Theme.inkSoft)
                        }
                        .card()
                    }.buttonStyle(PressableStyle())
                }
            }
            .padding(.horizontal, 18)
            .padding(.bottom, 40)
        }
        .background(Theme.paper.ignoresSafeArea())
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showSettings = true } label: { Image(systemName: "slider.horizontal.3") }
                    .accessibilityLabel("Settings")
            }
        }
        .toolbarBackground(.hidden, for: .navigationBar)
        .sheet(isPresented: $showSettings) { SettingsView() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                ScribiMark().fill(Theme.ink).frame(width: 44, height: 16).alignmentGuide(.firstTextBaseline) { d in d[.bottom] - 2 }
                Text("Scribi").font(Theme.display(40, weight: .medium)).foregroundStyle(Theme.ink)
                Spacer()
                NavigationLink(value: Route.connect) { StatusPill() }
            }
            let streak = app.progress.streak()
            let mastered = app.progress.count(.mastered)
            if streak > 0 || mastered > 0 {
                HStack(spacing: 16) {
                    Label("\(streak)-day streak", systemImage: "flame.fill").foregroundStyle(Theme.accent)
                    Label("\(mastered) mastered", systemImage: "checkmark.seal").foregroundStyle(Theme.inkSoft)
                }
                .font(Theme.sans(13, weight: .medium))
                .transition(.opacity)
            }
        }
        .padding(.top, 6)
    }
}

/// Glasses / server status, top right. Tapping opens the connect screen.
struct StatusPill: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: icon).font(.system(size: 12, weight: .semibold))
            Text(label).font(Theme.sans(12, weight: .semibold)).lineLimit(1)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(color.opacity(0.12), in: Capsule())
        .accessibilityLabel("Status: \(label)")
    }

    private var serverOK: Bool { app.link == .ok }

    private var label: String {
        if !serverOK { return app.hasServer ? "Server offline" : "Set up" }
        if app.demoMode { return "Demo mode" }
        switch app.glassesStatus {
        case .connected: return "Glasses on"
        case .connecting, .searching: return "Connecting"
        case .lost: return "Reconnecting"
        default: return "Phone camera"
        }
    }

    private var icon: String {
        if !serverOK { return "wifi.exclamationmark" }
        if app.demoMode { return "camera.viewfinder" }
        return app.glassesStatus.isConnected ? "eyeglasses" : "iphone"
    }

    private var color: Color {
        if !serverOK { return Theme.warn }
        return app.glassesStatus.isConnected || app.demoMode ? Theme.good : Theme.inkSoft
    }
}

struct LanguageCard: View {
    @Environment(AppModel.self) private var app
    let lesson: Lesson

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Text(lesson.name).font(Theme.sans(16, weight: .semibold)).foregroundStyle(Theme.ink)
                Spacer()
                Ring(value: app.progress.ring(for: lesson), lineWidth: 3.5).frame(width: 22, height: 22)
            }
            Text(ScriptInfo.hero(lesson.lang).isEmpty ? (lesson.phrases.first?.text ?? "") : ScriptInfo.hero(lesson.lang))
                .font(Theme.script(lesson.lang, size: 34))
                .foregroundStyle(Theme.ink)
                .lineLimit(1).minimumScaleFactor(0.5)
                .frame(maxWidth: .infinity, minHeight: 52, maxHeight: 52, alignment: lesson.isRTL ? .trailing : .leading)
                .environment(\.layoutDirection, lesson.isRTL ? .rightToLeft : .leftToRight)
                .padding(.vertical, 4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: 14)
        .accessibilityElement(children: .combine)
    }
}

struct FeatureCard: View {
    let symbol: String
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: symbol).font(.system(size: 22)).foregroundStyle(Theme.accent)
            Text(title).font(Theme.display(18)).foregroundStyle(Theme.ink)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card(padding: 14)
    }
}

struct VoiceHint: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: app.voice.state == .listening ? "waveform" : "mic.slash")
                .symbolEffect(.variableColor.iterative, isActive: app.voice.state == .listening)
                .foregroundStyle(app.voice.state == .listening ? Theme.accent : Theme.inkSoft)
            Text(app.voice.state == .listening
                 ? "Hands-free: say “next”, “again”, “slower”, “check”, “switch to Hebrew”, or “help me write good luck in Greek”."
                 : "Voice commands are off. Turn them on in Settings to practice hands-free.")
                .font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
        }
        .padding(.top, 4)
    }
}

/// Shown until lessons arrive: shimmer placeholders, not a spinner.
struct LoadingCards: View {
    @State private var pulse = false
    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)], spacing: 14) {
            ForEach(0..<6, id: \.self) { _ in
                RoundedRectangle(cornerRadius: Theme.corner, style: .continuous)
                    .fill(Theme.card).frame(height: 150)
                    .overlay(RoundedRectangle(cornerRadius: Theme.corner).strokeBorder(Theme.hairline))
                    .opacity(pulse ? 0.55 : 1)
            }
        }
        .onAppear { withAnimation(.easeInOut(duration: 0.9).repeatForever()) { pulse = true } }
        .accessibilityLabel("Loading lessons")
    }
}

/// First run / offline: where to point the app.
struct ServerCard: View {
    @Environment(AppModel.self) private var app
    @Binding var showSettings: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: app.hasServer ? "wifi.exclamationmark" : "laptopcomputer.and.iphone")
                .font(.system(size: 30)).foregroundStyle(Theme.accent)
            Text(app.hasServer ? "Can't reach the lesson server" : "Connect to your laptop")
                .font(Theme.display(24))
            Text(app.hasServer
                 ? "Tried \(app.serverAddress). Is the backend running, and is this phone on the same Wi-Fi?"
                 : "Scribi's lessons and grading run on the laptop. Enter its address once; it's remembered.")
                .font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
            if case .down(let msg) = app.link { Text(msg).font(Theme.sans(12)).foregroundStyle(Theme.inkSoft.opacity(0.8)) }
            Button(app.hasServer ? "Change address" : "Enter address") { showSettings = true }
                .buttonStyle(PrimaryButtonStyle())
                .padding(.top, 4)
        }
        .card(padding: 22)
    }
}
