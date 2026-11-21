import SwiftUI

/// What to practice, handed to the full-screen practice view.
struct PracticeLaunch: Identifiable {
    let id = UUID()
    let items: [PracticeItem]
    let mode: PracticeMode
    let title: String
}

struct LessonView: View {
    @Environment(AppModel.self) private var app
    let lang: String
    @State private var mode: PracticeMode = .write
    @State private var launch: PracticeLaunch?

    var body: some View {
        if let lesson = app.lesson(lang) {
            content(lesson)
        } else {
            ContentUnavailableView("Lesson not loaded", systemImage: "book.closed",
                                   description: Text("Check the lesson server in Settings."))
                .background(Theme.paper.ignoresSafeArea())
        }
    }

    private func content(_ lesson: Lesson) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header(lesson)
                Picker("Mode", selection: $mode) {
                    Text("Write along").tag(PracticeMode.write)
                    Text("From memory").tag(PracticeMode.dictation)
                }
                .pickerStyle(.segmented)

                Text(mode == .write
                     ? "Each stroke appears on your glasses. Write it on paper; the next one follows your pen."
                     : "You hear the word and see its meaning. Write it from memory, then see how you did.")
                    .font(Theme.sans(13)).foregroundStyle(Theme.inkSoft)

                VStack(spacing: 12) {
                    ForEach(lesson.phrases) { p in
                        Button { start(lesson, phrases: [p]) } label: { ItemRow(lesson: lesson, phrase: p) }
                            .buttonStyle(PressableStyle())
                    }
                }

                Button { start(lesson, phrases: lesson.phrases) } label: {
                    Label(mode == .write ? "Practice all \(lesson.phrases.count)" : "Quiz me on all \(lesson.phrases.count)",
                          systemImage: mode == .write ? "pencil.and.scribble" : "brain.head.profile")
                }
                .buttonStyle(PrimaryButtonStyle())

                NavigationLink(value: Route.journal(lesson.lang)) {
                    Label("Handwriting journal", systemImage: "book.pages").frame(maxWidth: .infinity)
                }
                .buttonStyle(QuietButtonStyle())
            }
            .padding(18)
            .padding(.bottom, 30)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle(lesson.name)
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $launch) { l in
            PracticeView(launch: l)
        }
    }

    private func header(_ lesson: Lesson) -> some View {
        let p = app.progress
        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(ScriptInfo.hero(lesson.lang))
                        .font(Theme.script(lesson.lang, size: 48))
                        .environment(\.layoutDirection, lesson.isRTL ? .rightToLeft : .leftToRight)
                        .lineLimit(1).minimumScaleFactor(0.5)
                    Text(lesson.script ?? ScriptInfo.script(lesson.lang)).font(Theme.sans(14, weight: .semibold)).foregroundStyle(Theme.accent)
                }
                Spacer()
                ZStack {
                    Ring(value: p.ring(for: lesson), lineWidth: 6)
                    Text("\(Int(p.ring(for: lesson) * 100))%").font(Theme.sans(13, weight: .semibold)).foregroundStyle(Theme.ink)
                }
                .frame(width: 64, height: 64)
            }
            if let about = lesson.about { Text(about).font(Theme.display(16)).foregroundStyle(Theme.ink.opacity(0.85)) }
            HStack(spacing: 14) {
                levelCount(.seen, lesson); levelCount(.practiced, lesson); levelCount(.mastered, lesson)
                Spacer()
                if lesson.isRTL { Label("Right to left", systemImage: "arrow.left").font(Theme.sans(12, weight: .medium)).foregroundStyle(Theme.inkSoft) }
            }
            if lesson.strokeOrder == "suggested" {
                Label("Suggested stroke order (hand-authored)", systemImage: "hand.draw").font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
            }
        }
        .card()
    }

    private func levelCount(_ level: CharProgress.Level, _ lesson: Lesson) -> some View {
        let n = Set(lesson.phrases.flatMap(\.chars)).filter { app.progress.progress(lesson.lang, $0).level == level }.count
        return VStack(alignment: .leading, spacing: 0) {
            Text("\(n)").font(Theme.display(20, weight: .medium))
            Text(level.label).font(Theme.sans(11)).foregroundStyle(Theme.inkSoft)
        }
    }

    private func start(_ lesson: Lesson, phrases: [Phrase]) {
        let items = phrases.flatMap { PracticeItem.all(lang: lesson.lang, phrase: $0) }
        guard !items.isEmpty else { return }
        launch = PracticeLaunch(items: items, mode: mode, title: phrases.count == 1 ? (phrases[0].meaning ?? phrases[0].text) : lesson.name)
    }
}

struct ItemRow: View {
    @Environment(AppModel.self) private var app
    let lesson: Lesson
    let phrase: Phrase

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(phrase.text)
                    .font(Theme.script(lesson.lang, size: 28))
                    .foregroundStyle(Theme.ink)
                    .environment(\.layoutDirection, lesson.isRTL ? .rightToLeft : .leftToRight)
                    .lineLimit(1).minimumScaleFactor(0.5)
                HStack(spacing: 8) {
                    if let r = phrase.romanization { Text(r).font(Theme.sans(14, weight: .medium)).foregroundStyle(Theme.accent) }
                    if let m = phrase.meaning { Text(m).font(Theme.sans(14)).foregroundStyle(Theme.inkSoft) }
                }
            }
            Spacer()
            HStack(spacing: 4) {
                ForEach(Array(phrase.chars.enumerated()), id: \.offset) { _, c in
                    LevelDot(level: app.progress.progress(lesson.lang, c).level)
                }
            }
            Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 14)
        .accessibilityElement(children: .combine)
    }
}

struct LevelDot: View {
    let level: CharProgress.Level
    var body: some View {
        Circle()
            .fill(level == .mastered ? Theme.good : level == .practiced ? Theme.accent : level == .seen ? Theme.inkSoft.opacity(0.5) : Color.clear)
            .overlay(Circle().strokeBorder(Theme.inkSoft.opacity(0.35), lineWidth: level == .new ? 1 : 0))
            .frame(width: 8, height: 8)
    }
}
