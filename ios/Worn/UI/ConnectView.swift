import SwiftUI

struct ConnectView: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        @Bindable var app = app
        ScrollView {
            VStack(spacing: 20) {
                hero
                switch app.glassesStatus {
                case .noSDK:
                    note("This build runs without the glasses SDK (simulator or standalone project). Demo Mode uses the phone camera and still reports every step to the live view.",
                         symbol: "info.circle")
                case .bluetoothOff:
                    note("Turn on Bluetooth in Control Center, then come back.", symbol: "exclamationmark.triangle")
                case .bluetoothUnauthorized:
                    note("Worn needs Bluetooth to reach your glasses. Allow it in Settings › Worn.", symbol: "lock")
                case .idle(let message):
                    if let message { note(message, symbol: "exclamationmark.circle") }
                    if let paired = app.glasses.pairedName {
                        Button("Connect to \(paired)") { app.glasses.connectPaired() }.buttonStyle(PrimaryButtonStyle())
                    }
                    Button(app.glasses.pairedName == nil ? "Find my glasses" : "Find other glasses") { app.glasses.search() }
                        .buttonStyle(app.glasses.pairedName == nil ? AnyButtonStyle(PrimaryButtonStyle()) : AnyButtonStyle(QuietButtonStyle()))
                case .searching:
                    deviceList
                    Button("Stop searching") { app.glasses.stopSearch() }.buttonStyle(QuietButtonStyle())
                case .connecting(let name):
                    ProgressView().controlSize(.large).padding(.top, 8)
                    Text("Talking to \(name)…").font(Theme.sans(15)).foregroundStyle(Theme.inkSoft)
                    Button("Cancel") { app.glasses.cancel() }.buttonStyle(QuietButtonStyle())
                case .connected(let name, let battery):
                    VStack(spacing: 6) {
                        Text(name).font(Theme.display(24))
                        if let battery { Label("\(battery)% battery", systemImage: "battery.75").font(Theme.sans(13)).foregroundStyle(Theme.inkSoft) }
                    }
                    Button("Disconnect") { app.glasses.disconnect() }.buttonStyle(QuietButtonStyle())
                case .lost(let attempt, let of):
                    ProgressView().padding(.top, 8)
                    Text("Lost the glasses. Reconnecting (\(attempt) of \(of))…").font(Theme.sans(15)).foregroundStyle(Theme.inkSoft)
                    Button("Stop and use the phone") { app.glasses.cancel(); app.demoMode = true }.buttonStyle(QuietButtonStyle())
                }

                Toggle(isOn: $app.demoMode) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Demo Mode").font(Theme.sans(16, weight: .semibold))
                        Text("No glasses: the phone camera watches the page.").font(Theme.sans(13)).foregroundStyle(Theme.inkSoft)
                    }
                }
                .tint(Theme.accent)
                .card()

                serverRow
            }
            .padding(18)
            .animation(.spring(response: 0.45, dampingFraction: 0.85), value: app.glassesStatus)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle("Glasses")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var hero: some View {
        let s = app.glassesStatus
        let color: Color = s.isConnected ? Theme.good : (s == .searching || { if case .connecting = s { return true }; return false }() ? Theme.accent : Theme.inkSoft)
        return VStack(spacing: 12) {
            ZStack {
                Circle().fill(color.opacity(0.12)).frame(width: 120, height: 120)
                Image(systemName: s.isConnected ? "eyeglasses" : "eyeglasses")
                    .font(.system(size: 48, weight: .light))
                    .foregroundStyle(color)
                    .symbolEffect(.pulse, isActive: s == .searching || { if case .connecting = s { return true }; if case .lost = s { return true }; return false }())
            }
            Text(s.title).font(Theme.display(26)).multilineTextAlignment(.center)
        }
        .padding(.top, 12)
    }

    @ViewBuilder
    private var deviceList: some View {
        if app.nearbyGlasses.isEmpty {
            HStack(spacing: 10) {
                ProgressView()
                Text("Looking nearby. Hold the glasses close to the phone.").font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
            }
            .card()
        } else {
            VStack(spacing: 0) {
                ForEach(app.nearbyGlasses) { d in
                    Button { app.glasses.connect(d) } label: {
                        HStack {
                            Image(systemName: "eyeglasses").foregroundStyle(Theme.accent)
                            VStack(alignment: .leading) {
                                Text(d.name).font(Theme.sans(16, weight: .medium)).foregroundStyle(Theme.ink)
                                Text(d.signal).font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
                            }
                            Spacer()
                            Text("Connect").font(Theme.sans(14, weight: .semibold)).foregroundStyle(Theme.accent)
                        }
                        .padding(.vertical, 10)
                    }
                    if d != app.nearbyGlasses.last { Divider() }
                }
            }
            .card(padding: 12)
        }
    }

    private var serverRow: some View {
        HStack {
            Image(systemName: app.link == .ok ? "checkmark.circle.fill" : "wifi.exclamationmark")
                .foregroundStyle(app.link == .ok ? Theme.good : Theme.warn)
            VStack(alignment: .leading, spacing: 2) {
                Text("Lesson server").font(Theme.sans(15, weight: .medium))
                Text(app.hasServer ? app.serverAddress : "Not set").font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
            }
            Spacer()
            if app.link != .ok { Button("Retry") { app.reconnect() }.font(Theme.sans(14, weight: .semibold)) }
        }
        .card()
    }

    private func note(_ text: String, symbol: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol).foregroundStyle(Theme.accent)
            Text(text).font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
            Spacer(minLength: 0)
        }
        .card()
    }
}

struct AnyButtonStyle: ButtonStyle {
    private let make: (Configuration) -> AnyView
    init<S: ButtonStyle>(_ s: S) { make = { AnyView(s.makeBody(configuration: $0)) } }
    func makeBody(configuration: Configuration) -> some View { make(configuration) }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""

    var body: some View {
        @Bindable var app = app
        NavigationStack {
            Form {
                Section {
                    TextField("192.168.1.20:8000", text: $address)
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit(save)
                    LabeledContent("Status") {
                        switch app.link {
                        case .ok: Text(app.health?.mock == true ? "Connected (mock)" : "Connected").foregroundStyle(Theme.good)
                        case .unknown: Text("Connecting…").foregroundStyle(Theme.inkSoft)
                        case .down: Text("Offline").foregroundStyle(Theme.warn)
                        }
                    }
                    if let ready = app.health?.modelReady {
                        LabeledContent("Grader", value: ready ? "Ready" : "Warming up")
                    }
                } header: { Text("Lesson server") } footer: {
                    Text("The laptop running the backend. On the laptop: ipconfig getifaddr en0. Port 8000 is added for you.")
                }
                Section("Practice") {
                    Toggle("Demo Mode (phone camera)", isOn: $app.demoMode)
                    Toggle("Voice commands", isOn: $app.voiceEnabled)
                    Toggle("Auto-advance", isOn: $app.autoAdvance)
                    Toggle("Confirm strokes with /stroke-match", isOn: $app.useStrokeMatch)
                }
                Section("Glasses") {
                    NavigationLink("Connect glasses") { ConnectView() }
                }
                Section {
                    Toggle("Latency overlay", isOn: $app.showDebug)
                    Button("Reset progress", role: .destructive) { app.progress = ProgressBook() }
                } header: { Text("Debug") }
                Section {
                    Text("Stroke order: hanzi-writer-data (Make Me a Hanzi, Arphic Public License). Hand-authored orders are marked “suggested”. Script fonts: Noto (SIL Open Font License).")
                        .font(.footnote).foregroundStyle(.secondary)
                } header: { Text("Credits") }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { save(); dismiss() } }
            }
            .onAppear { address = app.serverAddress }
        }
    }

    private func save() {
        if address != app.serverAddress { app.serverAddress = address } else { app.reconnect() }
    }
}

/// Per-tier latency and the last events, for judges and debugging.
struct DebugOverlay: View {
    @Environment(AppModel.self) private var app

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("LATENCY ms (last / avg)").font(.system(size: 9, weight: .bold, design: .monospaced))
            ForEach(Latency.Tier.allCases, id: \.self) { t in
                HStack(spacing: 6) {
                    Text(label(t)).frame(width: 74, alignment: .leading)
                    Text(app.latency.last[t].map(String.init) ?? "–").frame(width: 44, alignment: .trailing)
                    Text(app.latency.avg[t].map { String(Int($0)) } ?? "–").frame(width: 44, alignment: .trailing).opacity(0.7)
                }
            }
            Divider().overlay(Color.white.opacity(0.3))
            Text("source: \(app.photoSource.rawValue) · voice: \(String(describing: app.voice.state))")
            ForEach(Array(app.eventLog.suffix(5).enumerated()), id: \.offset) { _, e in
                Text("\(e.type) \(e.summary)").lineLimit(1)
            }
        }
        .font(.system(size: 10, design: .monospaced))
        .foregroundStyle(.white)
        .padding(8)
        .frame(width: 230, alignment: .leading)
        .background(.black.opacity(0.78), in: RoundedRectangle(cornerRadius: 10))
        .allowsHitTesting(false)
    }

    private func label(_ t: Latency.Tier) -> String {
        switch t {
        case .capture: return "capture"
        case .inkDiff: return "t1 ink"
        case .strokeMatch: return "t2 match"
        case .grade: return "t3 grade"
        case .nextStroke: return "pen→next"
        }
    }
}
