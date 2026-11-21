import SwiftUI

struct HomeView: View {
    @Environment(AppModel.self) private var app
    @State private var showSettings = false

    private var lessons: [Lesson] {
        app.lessons.sorted { (ScriptInfo.order.firstIndex(of: $0.lang) ?? 99) < (ScriptInfo.order.firstIndex(of: $1.lang) ?? 99) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                if !app.hasServer || (app.lessons.isEmpty && app.link != .unknown) {
                    ServerCard(showSettings: $showSettings)
                } else if app.lessons.isEmpty {
                    LoadingCards()
                } else {
                    today
                    section("Learn") {
                        VStack(spacing: 0) {
                            ForEach(Array(lessons.enumerated()), id: \.element.id) { i, l in
                                NavigationLink(value: Route.lesson(l.lang)) { LessonRow(lesson: l) }
                                    .buttonStyle(PressableStyle())
                                if i < lessons.count - 1 { Divider().overlay(Theme.hairline).padding(.leading, 76) }
                            }
                        }
                        .card(padding: 6)
                    }
                    section("Create") {
                        VStack(spacing: 0) {
                            NavigationLink(value: Route.name) { ToolRow(symbol: "signature", title: "Write your name") }
                                .buttonStyle(PressableStyle())
                            Divider().overlay(Theme.hairline).padding(.leading, 62)
                            NavigationLink(value: Route.compose) { ToolRow(symbol: "text.bubble", title: "Help me write") }
                                .buttonStyle(PressableStyle())
                        }
                        .card(padding: 6)
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 8)
            .padding(.bottom, 40)
        }
        .background(Theme.paper.ignoresSafeArea())
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                HStack(spacing: 8) {
                    ScribiMark().fill(Theme.ink).frame(width: 30, height: 11)
                    Text("Scribi").font(Theme.display(22, weight: .medium)).foregroundStyle(Theme.ink)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Scribi")
            }
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink(value: Route.connect) { StatusPill() }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { showSettings = true } label: { Image(systemName: "slider.horizontal.3") }
                    .accessibilityLabel("Settings")
            }
        }
        .toolbarBackground(.hidden, for: .navigationBar)
        .sheet(isPresented: $showSettings) { SettingsView() }
    }

    /// Today: the one thing to do next (Daily 5) plus streak and mastered at a glance.
    private var today: some View {
        NavigationLink(value: Route.daily) {
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Daily 5").font(Theme.display(26, weight: .medium)).foregroundStyle(.white)
                    HStack(spacing: 14) {
                        Label("\(app.progress.streak())", systemImage: "flame.fill")
                        Label("\(app.progress.count(.mastered))", systemImage: "checkmark.seal.fill")
                    }
                    .font(Theme.sans(16, weight: .semibold)).foregroundStyle(.white.opacity(0.9))
                }
                Spacer()
                Image(systemName: "play.fill").font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Theme.accent)
                    .frame(width: 52, height: 52)
                    .background(.white, in: Circle())
            }
            .padding(20)
            .background(Theme.accent, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        }
        .buttonStyle(PressableStyle())
        .accessibilityLabel("Start Daily 5")
    }

    private func section<C: View>(_ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(Theme.display(22, weight: .medium)).foregroundStyle(Theme.ink)
            content()
        }
    }
}

/// One script in the Learn list: big sample, name, progress ring.
struct LessonRow: View {
    @Environment(AppModel.self) private var app
    let lesson: Lesson

    var body: some View {
        HStack(spacing: 14) {
            Text(ScriptInfo.hero(lesson.lang).isEmpty ? (lesson.phrases.first?.text ?? "") : ScriptInfo.hero(lesson.lang))
                .font(Theme.script(lesson.lang, size: 26))
                .foregroundStyle(Theme.ink)
                .lineLimit(1).minimumScaleFactor(0.4)
                .frame(width: 58, height: 44)
            Text(lesson.name).font(Theme.sans(18, weight: .medium)).foregroundStyle(Theme.ink)
            Spacer()
            Ring(value: app.progress.ring(for: lesson), lineWidth: 3.5).frame(width: 24, height: 24)
            Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.inkSoft)
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

struct ToolRow: View {
    let symbol: String
    let title: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: symbol).font(.system(size: 20)).foregroundStyle(Theme.accent).frame(width: 36)
            Text(title).font(Theme.sans(18, weight: .medium)).foregroundStyle(Theme.ink)
            Spacer()
            Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.inkSoft)
        }
        .padding(.horizontal, 12).padding(.vertical, 16)
        .contentShape(Rectangle())
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
            if case .down(let msg) = app.link, !msg.contains("<") { Text(msg).font(Theme.sans(12)).foregroundStyle(Theme.inkSoft.opacity(0.8)) }
            Button(app.hasServer ? "Change address" : "Enter address") { showSettings = true }
                .buttonStyle(PrimaryButtonStyle())
                .padding(.top, 4)
        }
        .card(padding: 22)
    }
}
