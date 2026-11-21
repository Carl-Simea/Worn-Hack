import SwiftUI

/// Mirrors what's on the glasses: the current character, the grade, and controls.
struct LessonView: View {
    @Environment(AppModel.self) private var model
    @State private var showCamera = false

    var body: some View {
        if let s = model.session {
            content(s)
                .navigationTitle(model.currentLesson?.name ?? s.langName ?? s.lang)
                #if os(iOS)
                .navigationBarTitleDisplayMode(.inline)
                #endif
                .onDisappear { model.leaveLesson() }
                .sensoryFeedback(trigger: model.status) { _, new in
                    switch new {
                    case .correct: return .success
                    case .fix: return .warning
                    default: return nil
                    }
                }
                #if os(iOS)
                .sheet(isPresented: $showCamera) {
                    CameraPicker { model.gradeWithPhonePhoto($0) }.ignoresSafeArea()
                }
                #endif
        } else {
            ProgressView()
        }
    }

    @ViewBuilder
    private func content(_ s: SessionState) -> some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 20) {
                    if model.status == .lessonDone {
                        LessonSummary()
                    } else {
                        if let phrase = model.currentPhrase {
                            CharStrip(lang: s.lang, phrase: phrase, current: s.charIndex, rtl: s.isRTL)
                        }
                        Hero(session: s)
                        StatusCard(status: model.status)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
            }
            Controls(session: s, showCamera: $showCamera)
        }
    }
}

/// The phrase as a row of chars: done ones green, current one highlighted.
private struct CharStrip: View {
    @Environment(AppModel.self) private var model
    let lang: String
    let phrase: Phrase
    let current: Int
    let rtl: Bool

    var body: some View {
        HStack(spacing: 6) {
            ForEach(Array(phrase.chars.enumerated()), id: \.offset) { i, c in
                let score = model.best[AppModel.key(lang, phrase.id, i)]
                Text(c)
                    .font(.system(size: 30))
                    .frame(minWidth: 44, minHeight: 50)
                    .padding(.horizontal, 4)
                    .background(i == current ? Theme.accent.opacity(0.15) : Color.clear,
                                in: RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(i == current ? Theme.accent : Color.clear, lineWidth: 2))
                    .foregroundStyle(score.map { $0 >= 60 ? Theme.ok : Theme.fix } ?? (i == current ? .primary : .secondary))
            }
        }
        .environment(\.layoutDirection, rtl ? .rightToLeft : .leftToRight)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Character \(current + 1) of \(phrase.chars.count)")
    }
}

private struct Hero: View {
    @Environment(AppModel.self) private var model
    let session: SessionState

    var body: some View {
        VStack(spacing: 6) {
            Text(session.char ?? "")
                .font(.system(size: 150))
                .minimumScaleFactor(0.5)
                .lineLimit(1)
            HStack(spacing: 10) {
                if let r = session.romanization {
                    Text(r).font(.title3.weight(.semibold)).foregroundStyle(Theme.accent)
                }
                if session.audioUrl != nil {
                    Button { model.playAudioOnPhone() } label: {
                        Image(systemName: "speaker.wave.2.fill")
                    }
                    .accessibilityLabel("Play pronunciation on phone")
                }
            }
            if let m = session.meaning {
                Text("“\(m)”").font(.body).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

private struct StatusCard: View {
    let status: AppModel.Status

    var body: some View {
        VStack(spacing: 8) {
            switch status {
            case .waiting:
                Image(systemName: "eyeglasses").font(.system(size: 34)).foregroundStyle(Theme.accent)
                    .symbolEffect(.pulse)
                Text("Write it on paper, then press the glasses button.")
                    .multilineTextAlignment(.center)
            case .grading:
                ProgressView()
                Text("Checking your writing…").foregroundStyle(.secondary)
            case .correct(let r):
                Text("\(r.scoreInt)").font(.system(size: 54, weight: .bold).monospacedDigit()).foregroundStyle(Theme.ok)
                Label(r.feedback, systemImage: "checkmark.circle.fill").foregroundStyle(Theme.ok)
                    .multilineTextAlignment(.center)
            case .fix(let r):
                Text("\(r.scoreInt)").font(.system(size: 54, weight: .bold).monospacedDigit()).foregroundStyle(Theme.fix)
                Text(r.feedback).font(.headline).multilineTextAlignment(.center)
                if let seen = r.seen, !seen.isEmpty { Text("Read as: \(seen)").font(.footnote).foregroundStyle(.secondary) }
                Text("Try again, then press the glasses button.").font(.footnote).foregroundStyle(.secondary)
            case .lessonDone:
                EmptyView()
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, minHeight: 140)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 18))
        .animation(.snappy, value: status)
    }
}

private struct LessonSummary: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "party.popper.fill").font(.system(size: 48)).foregroundStyle(Theme.accent)
            Text("\(model.currentLesson?.name ?? "Lesson") complete").font(.title2.weight(.bold))
            if let lesson = model.currentLesson {
                VStack(spacing: 0) {
                    ForEach(lesson.phrases) { p in
                        HStack {
                            Text(p.text).environment(\.layoutDirection, lesson.isRTL ? .rightToLeft : .leftToRight)
                            Spacer()
                            Text(p.meaning ?? "").foregroundStyle(.secondary)
                            Text(model.bestScore(lang: lesson.lang, phrase: p).map(String.init) ?? "–")
                                .monospacedDigit().frame(width: 40, alignment: .trailing)
                        }
                        .padding(.vertical, 8)
                        Divider()
                    }
                }
            }
            Button("Start over") { model.restartLesson() }.buttonStyle(.borderedProminent)
        }
    }
}

private struct Controls: View {
    @Environment(AppModel.self) private var model
    let session: SessionState
    @Binding var showCamera: Bool

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                Button { model.previous() } label: { Label("Prev", systemImage: "chevron.backward").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered)
                Button { model.replayOnGlasses() } label: { Label("Replay", systemImage: "arrow.counterclockwise").frame(maxWidth: .infinity) }
                    .buttonStyle(.bordered)
                Button { model.next() } label: { Label("Next", systemImage: "chevron.forward").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
            }
            .controlSize(.large)
            #if os(iOS)
            Button { showCamera = true } label: { Label("Grade with phone", systemImage: "camera") }
                .font(.footnote)
            #endif
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.bar)
    }
}
