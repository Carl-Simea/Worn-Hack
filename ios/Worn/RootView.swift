import SwiftUI

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var showSettings = false

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Group {
                if !model.hasServer {
                    ConnectView()
                } else if model.lessons.isEmpty {
                    ConnectingView(showSettings: $showSettings)
                } else {
                    PickerView()
                }
            }
            .navigationTitle("Worn")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { showSettings = true } label: { LinkBadge(link: model.link) }
                        .accessibilityLabel("Server settings")
                }
            }
            .navigationDestination(isPresented: $model.showingLesson) { LessonView() }
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .alert("Heads up", isPresented: Binding(get: { model.lastError != nil }, set: { if !$0 { model.clearError() } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.lastError ?? "")
        }
    }
}

struct LinkBadge: View {
    let link: AppModel.Link

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label).font(.footnote.weight(.medium))
        }
        .foregroundStyle(.secondary)
    }

    private var color: Color {
        switch link {
        case .ok: return .green
        case .unknown: return .gray
        case .down: return .red
        }
    }

    private var label: String {
        switch link {
        case .ok: return "Glasses server"
        case .unknown: return "Connecting"
        case .down: return "Offline"
        }
    }
}

/// First launch: ask for the laptop's address.
struct ConnectView: View {
    @Environment(AppModel.self) private var model
    @State private var address = ""

    var body: some View {
        Form {
            Section {
                TextField("192.168.1.20:8000", text: $address)
                    .serverFieldStyle()
                    .onSubmit(save)
                Button("Connect", action: save).disabled(address.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Laptop server")
            } footer: {
                Text("Join the \"event\" wifi, then enter the laptop's IP. On the laptop, run: ipconfig getifaddr en0")
            }
        }
    }

    private func save() { model.serverAddress = address }
}

struct ConnectingView: View {
    @Environment(AppModel.self) private var model
    @Binding var showSettings: Bool

    var body: some View {
        VStack(spacing: 16) {
            if case .down(let msg) = model.link {
                Image(systemName: "wifi.exclamationmark").font(.system(size: 44)).foregroundStyle(.red)
                Text("Can't reach \(model.serverAddress)").font(.headline)
                Text(msg).font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Text("Is the laptop server running, and is this phone on the \"event\" wifi?")
                    .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                Button("Change address") { showSettings = true }.buttonStyle(.borderedProminent)
            } else {
                ProgressView()
                Text("Loading lessons…").foregroundStyle(.secondary)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section("Laptop server") {
                    TextField("192.168.1.20:8000", text: $address).serverFieldStyle()
                    LabeledContent("Status") { LinkBadge(link: model.link) }
                    if let ready = model.modelReady {
                        LabeledContent("Grader model", value: ready ? "Ready" : "Not loaded")
                    }
                }
                Section {
                    Toggle("Auto-advance when correct", isOn: $model.autoAdvance)
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        if address != model.serverAddress { model.serverAddress = address } else { model.reconnect() }
                        dismiss()
                    }
                }
            }
            .onAppear { address = model.serverAddress }
        }
    }
}

extension View {
    func serverFieldStyle() -> some View {
        #if os(iOS)
        return self.keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        return self.autocorrectionDisabled()
        #endif
    }
}
