import SwiftUI

@main
struct WornApp: App {
    @State private var app = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .tint(Theme.accent)
                .task { app.onLaunch() }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        NavigationStack(path: $app.route) {
            HomeView()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .lesson(let lang): LessonView(lang: lang)
                    case .compose: ComposeView()
                    case .name: NameView()
                    case .daily: DailyView()
                    case .journal(let lang): JournalView(lang: lang)
                    case .connect: ConnectView()
                    }
                }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { AppBar().ignoresSafeArea(.keyboard) }
        .sheet(isPresented: Binding(get: { app.pendingLaunch == nil && app.assistant.isOpen }, set: { if !$0 { app.assistant.close() } })) { AssistantView() }
        .sheet(item: Binding(get: { app.pendingLaunch == nil ? app.feedbackDraft : nil },
                             set: { if $0 == nil { app.feedbackDraft = nil } })) { FeedbackSheet(draft: $0) }
        .fullScreenCover(item: $app.pendingLaunch) { PracticeView(launch: $0) }
        .overlay(alignment: .topLeading) {
            if app.showDebug { DebugOverlay().padding(.top, 54).padding(.leading, 8) }
        }
    }
}
