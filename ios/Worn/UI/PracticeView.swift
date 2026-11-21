import AVFoundation
import SwiftUI

struct PracticeView: View {
    @Environment(AppModel.self) private var app
    @Environment(\.dismiss) private var dismiss
    let launch: PracticeLaunch
    @State private var engine: PracticeEngine?

    var body: some View {
        ZStack {
            Theme.paper.ignoresSafeArea()
            if let engine {
                PracticeContent(engine: engine, close: close)
            } else {
                ProgressView()
            }
        }
        .onAppear {
            guard engine == nil else { return }
            let e = PracticeEngine(app: app, items: launch.items, mode: launch.mode, title: launch.title,
                                   isName: launch.isName, adopted: launch.adoptedVersion != nil)
            engine = e
            e.start()
        }
        .onDisappear { engine?.stop() }
        .onChange(of: app.closePracticeRequest) { _, _ in close() }
        .sheet(item: Binding(get: { app.feedbackDraft }, set: { if $0 == nil { app.feedbackDraft = nil } })) { FeedbackSheet(draft: $0) }
    }

    private func close() {
        engine?.stop()
        dismiss()
    }
}

private struct PracticeContent: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            TopBar(engine: engine, close: close)
            if engine.phase == .finished {
                SummaryView(engine: engine, close: close)
            } else if let item = engine.current {
                ScrollView {
                    VStack(spacing: 16) {
                        CharacterCard(engine: engine, item: item)
                        StatusPanel(engine: engine, item: item)
                        HStack(alignment: .top, spacing: 12) {
                            if engine.source == .glasses { GlassesMirror(engine: engine, item: item) }
                            if engine.source == .phone { CameraCard(engine: engine) }
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .padding(.bottom, 16)
                }
                Controls(engine: engine)
            }
        }
        .overlay { ConfettiView(trigger: engine.confettiBurst).ignoresSafeArea() }
        .overlay(alignment: .top) {
            if let note = app.handoffNote {
                Label(note, systemImage: "arrow.triangle.2.circlepath")
                    .font(Theme.sans(13, weight: .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Theme.ink.opacity(0.88), in: Capsule())
                    .padding(.top, 58)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.5, dampingFraction: 0.8), value: app.handoffNote)
        .overlay(alignment: .top) {
            if let note = engine.notice {
                Label(note, systemImage: "iphone.rear.camera")
                    .font(Theme.sans(13, weight: .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 14).padding(.vertical, 9)
                    .background(Theme.ink.opacity(0.88), in: Capsule())
                    .padding(.top, 58)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.5, dampingFraction: 0.8), value: engine.notice)
        .overlay(alignment: .top) {
            if let m = engine.newMilestone { MilestoneBanner(milestone: m).padding(.top, 60).transition(.move(edge: .top).combined(with: .opacity)) }
        }
        .animation(.spring(response: 0.5, dampingFraction: 0.8), value: engine.newMilestone)
        .sensoryFeedback(trigger: engine.phase) { _, new in
            if case .result(let r) = new { return r.correct ? .success : .warning }
            return nil
        }
        .sensoryFeedback(.impact(weight: .light), trigger: engine.shownStroke)
    }
}

// MARK: top bar

private struct TopBar: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let close: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: close) {
                Image(systemName: "xmark").font(.system(size: 15, weight: .semibold)).frame(width: 36, height: 36)
                    .background(Theme.card, in: Circle()).overlay(Circle().strokeBorder(Theme.hairline))
            }
            .accessibilityLabel("Close practice")
            VStack(alignment: .leading, spacing: 4) {
                Text(engine.mode == .dictation ? "From memory · \(engine.title)" : engine.title)
                    .font(Theme.sans(14, weight: .semibold)).lineLimit(1)
                QueueDots(total: engine.queue.count, index: engine.index, outcomes: engine.outcomes)
            }
            Spacer()
            FeedbackButton(size: 40)
            SourceBadge(source: engine.source)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }
}

private struct QueueDots: View {
    let total: Int
    let index: Int
    let outcomes: [PracticeEngine.Outcome]

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<min(total, 24), id: \.self) { i in
                Capsule()
                    .fill(color(i))
                    .frame(width: i == index ? 16 : 6, height: 6)
            }
        }
        .animation(.spring(response: 0.4, dampingFraction: 0.7), value: index)
    }

    private func color(_ i: Int) -> Color {
        if i == index { return Theme.accent }
        if i < index { return outcomes.indices.contains(i) && outcomes[i].result?.correct == true ? Theme.good : Theme.inkSoft.opacity(0.5) }
        return Theme.hairline
    }
}

private struct MicBadge: View {
    @Environment(AppModel.self) private var app
    var body: some View {
        let on = app.voice.state == .listening
        Image(systemName: on ? "waveform" : "mic.slash")
            .font(.system(size: 14, weight: .semibold))
            .symbolEffect(.variableColor.iterative.reversing, isActive: on)
            .foregroundStyle(on ? Theme.accent : Theme.inkSoft)
            .frame(width: 32, height: 32)
            .background(Theme.card, in: Circle())
            .accessibilityLabel(on ? "Listening for voice commands" : "Voice commands off")
    }
}

private struct SourceBadge: View {
    let source: PhotoSource
    var body: some View {
        let glasses = source == .glasses
        Label(glasses ? "Glasses" : "Phone", systemImage: glasses ? "eyeglasses" : "iphone.rear.camera")
            .font(Theme.sans(12, weight: .semibold))
            .foregroundStyle(glasses ? Theme.good : Theme.inkSoft)
            .padding(.horizontal, 10).frame(height: 32)
            .background(Theme.card, in: Capsule())
    }
}

// MARK: character

private struct CharacterCard: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let item: PracticeItem

    var body: some View {
        VStack(spacing: 12) {
            HStack(spacing: 6) {
                arrow("chevron.left", label: "Previous stroke", enabled: canBack) { engine.back() }
                StrokeCanvas(lang: item.lang, char: item.char, strokes: engine.strokes,
                             shown: resultShowsAll ? 0 : engine.shownStroke, epoch: engine.strokeEpoch,
                             speed: engine.speed, hidden: !engine.revealed, numbers: engine.manual && engine.revealed)
                    .frame(maxWidth: engine.manual ? 280 : 236)
                    .id(item.id)
                    .transition(.asymmetric(insertion: .scale(scale: 0.9).combined(with: .opacity), removal: .opacity))
                arrow("chevron.right", label: "Next stroke", enabled: canNext) { engine.forward() }
            }
            .padding(.horizontal, 6)

            VStack(spacing: 4) {
                PhraseLine(item: item, revealed: engine.revealed)
                HStack(spacing: 10) {
                    if let r = item.phrase.romanization { Text(r).font(Theme.sans(17, weight: .semibold)).foregroundStyle(Theme.accent) }
                    if let m = item.phrase.meaning { Text("“\(m)”").font(Theme.display(17)).foregroundStyle(Theme.inkSoft) }
                    if let audio = item.phrase.audio, let url = app.api?.url(audio) {
                        Button { Sounds.shared.play(url: url, rate: engine.speed > 1.2 ? 0.8 : 1); app.report("audio.play", ["item": .string(item.phrase.id)]) } label: {
                            Image(systemName: "speaker.wave.2.fill").font(.system(size: 15))
                                .frame(width: 34, height: 34).background(Theme.accent.opacity(0.12), in: Circle())
                        }
                        .accessibilityLabel("Play pronunciation")
                    }
                }
            }
            if let note = noteLine {
                Text(note).font(Theme.sans(13)).foregroundStyle(Theme.inkSoft).multilineTextAlignment(.center)
                    .lineLimit(2).padding(.horizontal, 8)
            }
        }
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity)
        .card(padding: 8)
        .animation(.spring(response: 0.5, dampingFraction: 0.85), value: item.id)
    }

    private var showArrows: Bool { engine.phase == .writing && engine.mode != .dictation }
    private var canBack: Bool { engine.shownStroke > 1 }
    private var canNext: Bool { !engine.pacer.isOnLastStroke }

    /// Big round arrows beside the character: one stroke back / forward, any time.
    @ViewBuilder
    private func arrow(_ symbol: String, label: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        if showArrows {
            Button(action: action) {
                Image(systemName: symbol).font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(enabled ? Theme.ink : Theme.inkSoft.opacity(0.35))
                    .frame(width: 52, height: 52)
                    .background(Theme.card, in: Circle())
                    .overlay(Circle().strokeBorder(Theme.hairline))
            }
            .buttonStyle(PressableStyle())
            .disabled(!enabled)
            .accessibilityLabel(label)
        } else {
            Color.clear.frame(width: 52, height: 52)
        }
    }

    private var resultShowsAll: Bool { if case .result = engine.phase { return true }; return false }

    private var noteLine: String? {
        if engine.mode == .dictation && !engine.revealed { return item.phrase.dictation }
        if !engine.hasStrokeOrder { return "Trace the shape. Stroke order isn't standardized for this letter." }
        if engine.lesson?.strokeOrder == "suggested" { return "Suggested stroke order." }
        return item.charIndex == 0 ? item.phrase.how : nil
    }
}

/// The whole word, with the character being written highlighted.
private struct PhraseLine: View {
    let item: PracticeItem
    let revealed: Bool

    var body: some View {
        HStack(spacing: 2) {
            ForEach(Array(item.phrase.chars.enumerated()), id: \.offset) { i, c in
                Text(!revealed && i >= item.charIndex ? "·" : c)
                    .font(Theme.script(item.lang, size: 22))
                    .foregroundStyle(i == item.charIndex ? Theme.accent : (i < item.charIndex ? Theme.ink : Theme.inkSoft.opacity(0.5)))
                    .padding(.horizontal, 3)
                    .background(i == item.charIndex ? Theme.accent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 6))
            }
        }
        .environment(\.layoutDirection, ScriptInfo.isRTL(item.lang) ? .rightToLeft : .leftToRight)
        .lineLimit(1).minimumScaleFactor(0.5)
        .accessibilityLabel(revealed ? item.phrase.text : "Hidden word")
    }
}

// MARK: glasses mirror + camera

/// What's on the glasses right now (black is see-through on the optics).
private struct GlassesMirror: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let item: PracticeItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(engine.source == .glasses ? "On your glasses" : "Glasses view", systemImage: "eyeglasses")
                .font(Theme.sans(11, weight: .semibold)).foregroundStyle(Theme.inkSoft)
            ZStack {
                Theme.glassesBG
                Group {
                    if case .result(let r) = engine.phase {
                        VStack(spacing: 4) {
                            Image(systemName: r.correct ? "checkmark" : "arrow.uturn.backward")
                                .font(.system(size: 34, weight: .bold))
                                .foregroundStyle(r.correct ? Theme.glassesStroke : Color(red: 1, green: 0.8, blue: 0.4))
                            Text(r.correct ? "\(r.scoreInt)" : r.feedback).font(.system(size: 10, weight: .medium)).foregroundStyle(.white)
                                .lineLimit(2).multilineTextAlignment(.center).padding(.horizontal, 6)
                        }
                    } else {
                        StrokeCanvas(lang: item.lang, char: item.char, strokes: engine.strokes, shown: engine.shownStroke,
                                     epoch: engine.strokeEpoch, speed: engine.speed, style: .glasses, showGrid: false,
                                     hidden: !engine.revealed)
                            .padding(10)
                    }
                }
                VStack {
                    Spacer()
                    HStack {
                        Text(engine.mode == .dictation ? "from memory" : "\(engine.shownStroke)/\(max(1, engine.strokes?.count ?? 1))")
                        Spacer()
                        Text(item.phrase.romanization ?? "")
                    }
                    .font(.system(size: 9, weight: .semibold, design: .monospaced)).foregroundStyle(Theme.glassesStroke.opacity(0.8))
                    .hidden()
                    .padding(6)
                }
            }
            .aspectRatio(4.0 / 3.0, contentMode: .fit)   // 640×480 display
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .frame(maxWidth: .infinity)
    }
}

private struct CameraCard: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ZStack {
                if app.camera.usesSimulatedPage {
                    TimelineView(.periodic(from: .now, by: 0.5)) { _ in
                        if let img = app.camera.simulated.render(size: CGSize(width: 300, height: 400)) {
                            Image(decorative: img, scale: 1).resizable().scaledToFill()
                        }
                    }
                } else if app.camera.state == .running {
                    CameraPreview(session: app.camera.session)
                } else if app.camera.state == .unauthorized {
                    Text("Allow the camera in Settings").font(Theme.sans(11)).foregroundStyle(.white).padding(6)
                } else {
                    ProgressView().tint(.white)
                }
                // The writing box the ink detector watches.
                GeometryReader { g in
                    let w = g.size.width * 0.6, h = g.size.height * 0.6
                    RoundedRectangle(cornerRadius: 6)
                        .strokeBorder(Theme.accent, style: StrokeStyle(lineWidth: 2, dash: [6, 4]))
                        .frame(width: w, height: h)
                        .position(x: g.size.width / 2, y: g.size.height / 2)
                }
                if let ink = engine.lastInk, ink.unusable {
                    Text("Hold steady").font(Theme.sans(10, weight: .semibold)).foregroundStyle(.white)
                        .padding(4).background(.black.opacity(0.6), in: Capsule())
                }
            }
            .background(Color.black)
            .aspectRatio(4.0 / 3.0, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .frame(maxWidth: .infinity)
    }
}

struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.preview.session = session
        v.preview.videoGravity = .resizeAspectFill
        return v
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {}
}

// MARK: status

private struct StatusPanel: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let item: PracticeItem

    var body: some View {
        Group {
            switch engine.phase {
            case .starting:
                HStack(spacing: 10) { ProgressView(); Text("Getting the next one ready…").foregroundStyle(Theme.inkSoft) }
                    .frame(maxWidth: .infinity, minHeight: 92)
            case .writing:
                PacingStrip(engine: engine)
            case .checking:
                VStack(spacing: 10) {
                    InkDrops()
                    Text("Checking your writing…").font(Theme.display(18)).foregroundStyle(Theme.inkSoft)
                }
                .frame(maxWidth: .infinity, minHeight: 92)
            case .result(let r):
                ResultView(result: r, reaction: engine.reactionLine, engine: engine)
            case .failed(let message):
                VStack(spacing: 10) {
                    Image(systemName: "exclamationmark.triangle").foregroundStyle(Theme.warn).font(.system(size: 22))
                    Text(message).font(Theme.sans(14)).foregroundStyle(Theme.inkSoft).multilineTextAlignment(.center)
                    HStack {
                        Button("Try again") { engine.again() }.buttonStyle(QuietButtonStyle())
                        Button("Skip") { engine.skip() }.buttonStyle(QuietButtonStyle())
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 92)
            case .finished:
                EmptyView()
            }
        }
        .card()
        .animation(.spring(response: 0.45, dampingFraction: 0.85), value: engine.phase)
    }
}

/// "Stroke 3 of 7", with the three ways it moves on: your pen, your voice, or the timer.
private struct PacingStrip: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine

    var body: some View {
        if engine.manual { stepBody } else { autoBody }
    }

    /// Step by step: you decide when the next stroke appears.
    private var stepBody: some View {
        let n = max(1, engine.strokes?.count ?? 1)
        return VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("Stroke \(engine.shownStroke)").font(Theme.display(30, weight: .medium)).contentTransition(.numericText())
                Text("of \(n)").font(Theme.display(20)).foregroundStyle(Theme.inkSoft)
                Spacer()
            }
            if n > 1 {
                HStack(spacing: 5) {
                    ForEach(1...n, id: \.self) { i in
                        Capsule().fill(i < engine.shownStroke ? Theme.ink : (i == engine.shownStroke ? Theme.accent : Theme.hairline))
                            .frame(height: 8)
                    }
                }
            }
            Label(trackingLine, systemImage: engine.followPen ? (engine.trackState == .writing ? "pencil.line" : "eye") : "hand.tap")
                .font(Theme.sans(16, weight: .medium)).foregroundStyle(engine.trackState == .writing && engine.followPen ? Theme.accent : Theme.inkSoft)
                .contentTransition(.symbolEffect(.replace))
            Button { engine.setFollowPen(!engine.followPen) } label: {
                Label(engine.followPen ? "Pen tracking on" : "Pen tracking off", systemImage: engine.followPen ? "checkmark.circle.fill" : "circle")
            }
            .font(Theme.sans(15, weight: .semibold))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: engine.shownStroke)
    }

    private var trackingLine: String {
        guard engine.followPen else { return "Use the arrows or say “next”." }
        if engine.trackState == .writing { return "Writing… I move on when you lift the pen." }
        return engine.pacer.isOnLastStroke ? "Write the last stroke, then tap Check." : "Watching your page. Arrows or “next” also work."
    }

    private var autoBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                if engine.mode == .dictation {
                    Text("Write it from memory").font(Theme.display(20))
                } else {
                    Text("Stroke \(engine.shownStroke)").font(Theme.display(24, weight: .medium))
                        .contentTransition(.numericText())
                    Text("of \(max(1, engine.strokes?.count ?? 1))").font(Theme.display(18)).foregroundStyle(Theme.inkSoft)
                }
                Spacer()
                ZStack {
                    Ring(value: engine.pacer.timeoutProgress(now: engine.now), lineWidth: 3, color: Theme.inkSoft.opacity(0.6))
                    Image(systemName: "timer").font(.system(size: 10)).foregroundStyle(Theme.inkSoft)
                }
                .frame(width: 26, height: 26)
                .accessibilityLabel("Moves on automatically")
            }
            HStack(spacing: 8) {
                chip("pencil.tip", "Your pen", active: engine.lastTrigger == .ink)
                chip("waveform", "“next”", active: engine.lastTrigger == .voice)
                chip("timer", "\(Int(engine.pacer.timeout))s", active: engine.lastTrigger == .timeout)
                Spacer(minLength: 0)
            }
            Text(hint).font(Theme.sans(13)).foregroundStyle(Theme.inkSoft)
            if engine.mode != .dictation {
                Button { engine.setStepByStep(true) } label: { Label("Step by step", systemImage: "list.number") }
                    .font(Theme.sans(15, weight: .semibold))
            }
            if engine.source == .glasses {
                Button { engine.switchToPhoneCamera() } label: {
                    Label("Use phone camera", systemImage: "iphone.rear.camera")
                }
                .font(Theme.sans(13, weight: .semibold))
            }
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.8), value: engine.shownStroke)
    }

    private var hint: String {
        if engine.mode == .dictation { return "Say “check” when you're done, or just put the pen down." }
        if engine.source == .glasses { return "Write on paper in front of you. The glasses watch and show the next stroke." }
        if app.camera.usesSimulatedPage { return "Simulator: a pretend pen writes each stroke so you can watch the loop." }
        return "Keep the page inside the dashed box. The next stroke follows your pen."
    }

    private func chip(_ symbol: String, _ text: String, active: Bool) -> some View {
        Label(text, systemImage: symbol)
            .font(Theme.sans(12, weight: .semibold))
            .foregroundStyle(active ? .white : Theme.inkSoft)
            .padding(.horizontal, 10).frame(height: 28)
            .background(active ? Theme.accent : Theme.paper, in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: active ? 0 : 1))
            .scaleEffect(active ? 1.06 : 1)
    }
}

private struct ResultView: View {
    let result: GradeResult
    let reaction: String?
    let engine: PracticeEngine
    @State private var shownScore = 0

    var body: some View {
        VStack(spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(shownScore)")
                    .font(Theme.display(56, weight: .medium))
                    .foregroundStyle(result.correct ? Theme.good : Theme.warn)
                    .contentTransition(.numericText(value: Double(shownScore)))
                Text("/ 100").font(Theme.sans(15)).foregroundStyle(Theme.inkSoft)
            }
            if let reaction { Text(reaction).font(Theme.display(19)).multilineTextAlignment(.center) }
            if !result.correct || reaction == nil {
                Text(result.feedback).font(Theme.sans(14)).foregroundStyle(Theme.inkSoft).multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .onAppear {
            withAnimation(.spring(response: 0.9, dampingFraction: 0.9)) { shownScore = result.scoreInt }
        }
    }
}

/// Three ink drops while the model reads the page.
private struct InkDrops: View {
    @State private var phase = false
    var body: some View {
        HStack(spacing: 8) {
            ForEach(0..<3, id: \.self) { i in
                Circle().fill(Theme.accent).frame(width: 10, height: 10)
                    .offset(y: phase ? -6 : 4)
                    .animation(.easeInOut(duration: 0.5).repeatForever().delay(Double(i) * 0.15), value: phase)
            }
        }
        .onAppear { phase = true }
    }
}

// MARK: controls

private struct Controls: View {
    let engine: PracticeEngine

    var body: some View {
        HStack(spacing: 10) {
            if engine.manual && engine.phase == .writing {
                Button { engine.replay() } label: { Label("Replay", systemImage: "arrow.counterclockwise").labelStyle(.iconOnly) }
                    .buttonStyle(QuietButtonStyle())
            } else {
                Button { engine.again() } label: { Label("Again", systemImage: "arrow.counterclockwise").labelStyle(.iconOnly) }
                    .buttonStyle(QuietButtonStyle())
                Button { engine.slower() } label: { Label("Slower", systemImage: "tortoise").labelStyle(.iconOnly) }
                    .buttonStyle(QuietButtonStyle())
                    .disabled(engine.phase != .writing)
            }
            Spacer(minLength: 0)
            VoiceButton(size: 54)
            switch engine.phase {
            case .writing:
                Button(engine.mode == .dictation || engine.pacer.isOnLastStroke ? "Check" : "Next stroke") {
                    if engine.mode == .dictation || engine.pacer.isOnLastStroke { engine.check() } else { engine.next() }
                }
                .buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 150)
            case .result, .failed:
                Button(engine.isLast ? "Finish" : "Next") { engine.next() }.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 150)
            default:
                Button("…") {}.buttonStyle(PrimaryButtonStyle()).frame(maxWidth: 150).disabled(true).opacity(0.5)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.bar)
    }
}

// MARK: summary + milestone

private struct SummaryView: View {
    @Environment(AppModel.self) private var app
    let engine: PracticeEngine
    let close: () -> Void

    private var average: Int {
        let s = engine.outcomes.compactMap { $0.result?.scoreInt }
        return s.isEmpty ? 0 : s.reduce(0, +) / s.count
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                Image(systemName: "seal.fill").font(.system(size: 54)).foregroundStyle(Theme.accent).symbolEffect(.bounce, value: engine.outcomes.count)
                Text("Well written").font(Theme.display(34, weight: .medium))
                Text("\(engine.outcomes.count) \(engine.outcomes.count == 1 ? "character" : "characters") · average \(average)")
                    .font(Theme.sans(15)).foregroundStyle(Theme.inkSoft)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 72), spacing: 10)], spacing: 10) {
                    ForEach(engine.outcomes) { o in
                        VStack(spacing: 4) {
                            Text(o.item.char).font(Theme.script(o.item.lang, size: 30)).lineLimit(1).minimumScaleFactor(0.4)
                            Text(o.result.map { "\($0.scoreInt)" } ?? "–").font(Theme.sans(12, weight: .semibold))
                                .foregroundStyle(o.result?.correct == true ? Theme.good : Theme.warn)
                        }
                        .frame(maxWidth: .infinity, minHeight: 72)
                        .card(padding: 8)
                    }
                }
                Button("Done", action: close).buttonStyle(PrimaryButtonStyle())
            }
            .padding(20)
        }
        .onAppear { if average >= 85 { Sounds.shared.effect(.tada) } }
    }
}

private struct MilestoneBanner: View {
    let milestone: EarnedMilestone
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "rosette").font(.system(size: 26)).foregroundStyle(Theme.accent)
                .symbolEffect(.bounce, value: milestone.id)
            VStack(alignment: .leading, spacing: 2) {
                Text(milestone.line.shown ?? "Milestone").font(Theme.display(18, weight: .medium))
                Text(milestone.line.spoken).font(Theme.sans(13)).foregroundStyle(Theme.inkSoft)
            }
            Spacer()
        }
        .card()
        .shadow(color: .black.opacity(0.12), radius: 18, y: 8)
        .padding(.horizontal, 16)
    }
}
