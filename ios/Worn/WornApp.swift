import SwiftUI

@main
struct WornApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .tint(Theme.accent)
        }
    }
}

enum Theme {
    static let accent = Color(red: 0.04, green: 0.52, blue: 1.0)
    static let ok = Color.green
    static let fix = Color.orange
}
