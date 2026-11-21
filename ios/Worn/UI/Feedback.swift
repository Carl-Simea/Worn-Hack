import SwiftUI
import UIKit

/// One feedback report: the screen as it was, plus everything the app knew at that moment.
/// It is written to Documents/Feedback/<time>/ the moment the flag is tapped; the note and the marked-up
/// screenshot are added when the learner taps Save. `ios/scripts/pull-feedback.sh` copies the folders to the Mac.
struct FeedbackDraft: Identifiable {
    let id = UUID()
    let screenshot: UIImage
    let context: [(String, String)]
    let folder: URL
}

enum FeedbackStore {
    static var root: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("Feedback", isDirectory: true)
    }

    static func capture() -> UIImage? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first,
              let window = scene.windows.first(where: { $0.isKeyWindow }) ?? scene.windows.first else { return nil }
        let r = UIGraphicsImageRenderer(bounds: window.bounds)
        return r.image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: false) }
    }

    /// Creates the folder and saves screenshot + context right away.
    static func save(screenshot: UIImage, context: [(String, String)]) -> URL {
        let f = DateFormatter(); f.dateFormat = "yyyyMMdd-HHmmss"
        let folder = root.appendingPathComponent(f.string(from: Date()), isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try? screenshot.pngData()?.write(to: folder.appendingPathComponent("screenshot.png"))
        var obj: [String: String] = [:]
        for (k, v) in context { obj[k] = v }
        if let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: folder.appendingPathComponent("context.json"))
        }
        let text = context.map { "\($0.0): \($0.1)" }.joined(separator: "\n")
        try? text.write(to: folder.appendingPathComponent("context.txt"), atomically: true, encoding: .utf8)
        return folder
    }
}

extension AppModel {
    /// Takes the screenshot first (before the sheet covers it), collects context, saves, then opens the window.
    func startFeedback() {
        guard feedbackDraft == nil, let shot = FeedbackStore.capture() else { return }
        let ctx = feedbackContext()
        let folder = FeedbackStore.save(screenshot: shot, context: ctx)
        report("feedback.open", ["folder": .string(folder.lastPathComponent)])
        feedbackDraft = FeedbackDraft(screenshot: shot, context: ctx, folder: folder)
    }

    func feedbackContext() -> [(String, String)] {
        var c: [(String, String)] = []
        let iso = ISO8601DateFormatter()
        c.append(("time", iso.string(from: Date())))
        let info = Bundle.main.infoDictionary
        c.append(("app", "\(info?["CFBundleDisplayName"] as? String ?? "?") \(info?["CFBundleShortVersionString"] as? String ?? "?") (\(info?["CFBundleVersion"] as? String ?? "?"))"))
        c.append(("device", "\(UIDevice.current.model) iOS \(UIDevice.current.systemVersion)"))
        c.append(("screen", "\(Int(UIScreen.main.bounds.width))x\(Int(UIScreen.main.bounds.height)) pt"))
        c.append(("route", route.isEmpty ? "home" : route.map { "\($0)" }.joined(separator: " > ")))
        if let p = practice {
            c.append(("practice", "\(p.title) · mode \(p.mode.rawValue) · phase \(Self.phaseName(p.phase)) · step-by-step \(p.stepByStep ? "on" : "off")"))
            if let item = p.current {
                c.append(("character", "\(item.char) (\(item.lang), item \(item.phrase.id), char \(item.charIndex + 1)/\(item.phrase.chars.count))"))
            }
            c.append(("stroke", "\(p.shownStroke) of \(p.strokes?.count ?? 0) · data \(p.strokes == nil ? "none" : "loaded") · last trigger \(p.lastTrigger?.rawValue ?? "-") · speed \(String(format: "%.2f", p.speed))"))
            c.append(("photo source", p.source.rawValue))
            if case .result(let r) = p.phase {
                let u: (String?) -> String = { path in path.flatMap { self.api?.url($0)?.absoluteString } ?? "-" }
                c.append(("grade", "status \(r.status ?? "?") · score \(r.score.map { String(Int($0)) } ?? "none") · correct \(r.correct) · weakest \(r.weakest ?? "-") · seen “\(r.seen ?? "")”"))
                c.append(("grade subscores", (r.subscores ?? [:]).sorted { $0.key < $1.key }.map { "\($0.key) \(Int($0.value))" }.joined(separator: ", ")))
                c.append(("grade feedback", r.feedback))
                c.append(("photo sent (full)", u(r.imageUrl)))
                c.append(("photo checked (crop)", u(r.cropUrl)))
            }
        } else {
            c.append(("practice", "none"))
        }
        c.append(("voice", "\(voiceEnabled ? "on" : "off") · \(String(describing: voice.state)) · heard “\(voice.lastHeard)” · last command \(voice.lastCommand.map { "\($0)" } ?? "-")"))
        c.append(("server", "\(link) · host \(URL(string: serverAddress)?.host ?? serverAddress)"))
        c.append(("mode", "\(demoMode ? "demo" : "glasses") · glasses \(glassesStatus.title) · lessons \(lessons.count)"))
        let recent = eventLog.suffix(25).map { e in
            "\(DateFormatter.localizedString(from: e.ts, dateStyle: .none, timeStyle: .medium)) \(e.type) \(e.summary)"
        }
        c.append(("recent events", "\n" + recent.joined(separator: "\n")))
        return c
    }

    private static func phaseName(_ p: PracticeEngine.Phase) -> String {
        switch p {
        case .starting: return "starting"
        case .writing: return "writing"
        case .checking: return "checking"
        case .result(let r): return "result \(r.scoreInt)"
        case .failed(let m): return "failed (\(m))"
        case .finished: return "finished"
        }
    }
}

/// The feedback window: the screenshot (draw on it to point at the problem), one line of text, Save.
struct FeedbackSheet: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    let draft: FeedbackDraft
    @State private var lines: [[CGPoint]] = []
    @State private var current: [CGPoint] = []
    @State private var note = ""
    @State private var saved = false
    @State private var viewSize: CGSize = .zero
    @FocusState private var typing: Bool

    private var aspect: CGFloat { draft.screenshot.size.width / max(1, draft.screenshot.size.height) }

    var body: some View {
        VStack(spacing: 14) {
            HStack {
                Button("Close") { dismiss() }.font(Theme.sans(17))
                Spacer()
                Text("Show what's wrong").font(Theme.sans(17, weight: .semibold))
                Spacer()
                Button { if !lines.isEmpty { lines.removeLast() } } label: { Image(systemName: "arrow.uturn.backward") }
                    .disabled(lines.isEmpty).frame(width: 48, alignment: .trailing)
            }
            .padding(.horizontal, 20).padding(.top, 16)

            GeometryReader { geo in
                let size = fit(in: geo.size)
                ZStack {
                    Image(uiImage: draft.screenshot).resizable().frame(width: size.width, height: size.height)
                    marks(size: size)
                        .frame(width: size.width, height: size.height)
                        .contentShape(Rectangle())
                        .gesture(DragGesture(minimumDistance: 0)
                            .onChanged { current.append(clamp($0.location, size)) }
                            .onEnded { _ in if !current.isEmpty { lines.append(current) }; current = [] })
                }
                .frame(width: size.width, height: size.height)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.hairline))
                .position(x: geo.size.width / 2, y: geo.size.height / 2)
                .onAppear { viewSize = size }
                .onChange(of: geo.size) { _, _ in viewSize = size }
            }
            .padding(.horizontal, 20)

            TextField("What's wrong?", text: $note, axis: .vertical)
                .focused($typing)
                .font(Theme.sans(17))
                .lineLimit(1...3)
                .padding(14)
                .background(Theme.card, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Theme.hairline))
                .padding(.horizontal, 20)

            if saved {
                Label("Saved", systemImage: "checkmark.circle.fill").font(Theme.sans(17, weight: .semibold)).foregroundStyle(Theme.good)
                    .frame(height: 54)
            } else {
                Button("Save") { save() }.buttonStyle(PrimaryButtonStyle()).padding(.horizontal, 20)
            }
            Spacer(minLength: 0).frame(height: 8)
        }
        .background(Theme.paper.ignoresSafeArea())
        .presentationDetents([.large])
        .interactiveDismissDisabled(false)
        .onDisappear { app.feedbackDraft = nil }
    }

    // MARK: drawing

    private func fit(in avail: CGSize) -> CGSize {
        let h = min(avail.height, avail.width / aspect)
        return CGSize(width: h * aspect, height: h)
    }

    private func clamp(_ p: CGPoint, _ s: CGSize) -> CGPoint { CGPoint(x: min(max(0, p.x), s.width), y: min(max(0, p.y), s.height)) }

    private func marks(size: CGSize) -> some View {
        Canvas { ctx, _ in
            for l in lines + [current] where l.count > 0 {
                var p = Path(); p.addLines(l)
                ctx.stroke(p, with: .color(.red), style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
                if l.count == 1 { ctx.fill(Path(ellipseIn: CGRect(x: l[0].x - 4, y: l[0].y - 4, width: 8, height: 8)), with: .color(.red)) }
            }
        }
    }

    // MARK: save

    private func save() {
        typing = false
        let size = draft.screenshot.size
        let k = size.width / max(1, viewSize.width)   // view points → screenshot points
        let r = UIGraphicsImageRenderer(size: size)
        let marked = r.image { c in
            draft.screenshot.draw(at: .zero)
            c.cgContext.setStrokeColor(UIColor.red.cgColor)
            c.cgContext.setLineWidth(5)
            c.cgContext.setLineCap(.round); c.cgContext.setLineJoin(.round)
            for l in lines where !l.isEmpty {
                c.cgContext.beginPath()
                c.cgContext.move(to: CGPoint(x: l[0].x * k, y: l[0].y * k))
                for p in l.dropFirst() { c.cgContext.addLine(to: CGPoint(x: p.x * k, y: p.y * k)) }
                if l.count == 1 { c.cgContext.addEllipse(in: CGRect(x: l[0].x * k - 4, y: l[0].y * k - 4, width: 8, height: 8)) }
                c.cgContext.strokePath()
            }
        }
        try? marked.pngData()?.write(to: draft.folder.appendingPathComponent("marked.png"))
        try? note.write(to: draft.folder.appendingPathComponent("note.txt"), atomically: true, encoding: .utf8)
        app.report("feedback", ["folder": .string(draft.folder.lastPathComponent), "note": .string(note), "marks": .int(lines.count)])
        withAnimation { saved = true }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        Task { try? await Task.sleep(for: .seconds(0.9)); dismiss() }
    }
}
