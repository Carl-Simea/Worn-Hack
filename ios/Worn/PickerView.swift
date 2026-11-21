import SwiftUI

/// Pick a language and a phrase. Tapping a phrase sends it to the glasses.
struct PickerView: View {
    @Environment(AppModel.self) private var model
    @State private var selectedLang: String?
    @State private var mode: Mode = .write

    private var lesson: Lesson? {
        model.lessons.first { $0.lang == selectedLang } ?? model.lessons.first
    }

    var body: some View {
        List {
            Section {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(model.lessons) { l in
                            LangChip(title: l.name, on: l.lang == lesson?.lang) { selectedLang = l.lang }
                        }
                    }
                    .padding(.vertical, 4)
                }
                .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))

                if let lesson, !lesson.isASL {
                    Picker("Mode", selection: $mode) {
                        Label("Write", systemImage: "pencil.and.scribble").tag(Mode.write)
                        Label("Sign (ASL)", systemImage: "hand.raised").tag(Mode.asl)
                    }
                    .pickerStyle(.segmented)
                }
            }

            if let lesson {
                Section {
                    ForEach(lesson.phrases) { p in
                        Button {
                            model.start(lang: lesson.lang, phraseId: p.id, mode: lesson.isASL ? .asl : mode)
                        } label: {
                            PhraseRow(lesson: lesson, phrase: p, mode: lesson.isASL ? .asl : mode,
                                      best: model.bestScore(lang: lesson.lang, phrase: p))
                        }
                        .foregroundStyle(.primary)
                    }
                } header: {
                    Text(lesson.isASL || mode == .asl ? "Tap a phrase: the sign plays on your glasses"
                                                      : "Tap a phrase: stroke order plays on your glasses")
                }
            }
        }
        .onAppear { if selectedLang == nil { selectedLang = model.session?.lang ?? model.lessons.first?.lang } }
    }
}

struct LangChip: View {
    let title: String
    let on: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline.weight(.medium))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(on ? Theme.accent : Color.secondary.opacity(0.12), in: Capsule())
                .foregroundStyle(on ? Color.white : Color.primary)
        }
        .buttonStyle(.plain)
    }
}

struct PhraseRow: View {
    let lesson: Lesson
    let phrase: Phrase
    let mode: Mode
    let best: Int?

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(phrase.text)
                    .font(.system(size: lesson.isASL ? 20 : 28, weight: lesson.isASL ? .semibold : .regular))
                    .environment(\.layoutDirection, lesson.isRTL ? .rightToLeft : .leftToRight)
                if let r = phrase.romanization, mode == .write {
                    Text(r).font(.subheadline).foregroundStyle(Theme.accent)
                }
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(phrase.meaning ?? phrase.id).font(.subheadline).foregroundStyle(.secondary)
                if let best, mode == .write {
                    Text("\(best)").font(.caption.weight(.bold).monospacedDigit())
                        .padding(.horizontal, 8).padding(.vertical, 2)
                        .background((best >= 60 ? Theme.ok : Theme.fix).opacity(0.18), in: Capsule())
                        .foregroundStyle(best >= 60 ? Theme.ok : Theme.fix)
                }
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
    }
}
