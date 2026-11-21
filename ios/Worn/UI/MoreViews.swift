import SwiftUI

// MARK: Help me write…

struct ComposeView: View {
    @Environment(AppModel.self) private var app
    @State private var text = ""
    @State private var lang = "mandarin"
    @State private var result: ComposeResult?
    @State private var session: SessionState?
    @State private var loading = false
    @State private var error: String?
    @State private var launch: PracticeLaunch?
    @FocusState private var focused: Bool

    private let suggestions = ["good luck", "happy birthday", "see you soon", "welcome", "thank you, friend"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Help me write…").font(Theme.display(30, weight: .medium))
                Text("Type or say a short message. Scribi translates it, puts it on your glasses, and guides you stroke by stroke.")
                    .font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)

                TextField("happy birthday", text: $text, axis: .vertical)
                    .font(Theme.display(22))
                    .focused($focused)
                    .submitLabel(.go)
                    .onSubmit(compose)
                    .card()

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(suggestions, id: \.self) { s in
                            Button(s) { text = s; compose() }.buttonStyle(QuietButtonStyle())
                        }
                    }
                }

                LangPicker(selection: $lang)

                Button(action: compose) {
                    if loading {
                        HStack(spacing: 10) { ProgressView().tint(.white); Text("Translating…") }
                    } else {
                        Label("Translate", systemImage: "character.book.closed")
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
                .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty || loading)

                if let error { Label(error, systemImage: "exclamationmark.triangle").font(Theme.sans(13)).foregroundStyle(Theme.warn) }

                if let r = result {
                    VStack(alignment: .leading, spacing: 10) {
                        Eyebrow(text: app.lesson(lang)?.name ?? lang)
                        Text(r.native).font(Theme.script(lang, size: 44))
                            .environment(\.layoutDirection, ScriptInfo.isRTL(lang) ? .rightToLeft : .leftToRight)
                            .frame(maxWidth: .infinity, alignment: ScriptInfo.isRTL(lang) ? .trailing : .leading)
                            .textSelection(.enabled)
                        if let rom = r.romanization { Text(rom).font(Theme.sans(17, weight: .semibold)).foregroundStyle(Theme.accent) }
                        if let back = r.backTranslation { Text("Means: “\(back)”").font(Theme.display(16)).foregroundStyle(Theme.inkSoft) }
                        if let note = r.note { Text(note).font(Theme.sans(12)).foregroundStyle(Theme.inkSoft) }
                        Button(action: startWriting) { Label("Write it, stroke by stroke", systemImage: "pencil.and.scribble") }
                            .buttonStyle(PrimaryButtonStyle())
                            .disabled(r.chars.isEmpty)
                    }
                    .card()
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .padding(18)
            .animation(.spring(response: 0.5, dampingFraction: 0.85), value: result)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $launch) { PracticeView(launch: $0) }
        .onAppear {
            if let p = app.pendingCompose {
                text = p.text
                if let l = p.lang, app.lesson(l) != nil { lang = l }
                app.pendingCompose = nil
                compose()
            } else if app.lesson(lang) == nil, let first = app.lessons.first {
                lang = first.lang
            }
        }
    }

    /// POST /session with mode "compose": the server translates, stores the item (so the glasses can show it),
    /// and answers with its item_id. Falls back to POST /compose (phone-only) if that fails.
    private func compose() {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, let api = app.api else { return }
        focused = false
        loading = true; error = nil; session = nil
        app.report("compose.start", ["text": .string(t), "lang": .string(lang)])
        Task {
            do {
                let s = try await api.startSession(SessionRequest(composing: t, lang: lang))
                app.noteOwnSession(s)
                session = s
                result = ComposeResult(session: s)
            } catch {
                do { result = try await api.compose(text: t, lang: lang) } catch {
                    self.error = error.localizedDescription
                }
            }
            if let r = result {
                app.report("compose", ["text": .string(t), "lang": .string(lang), "native": .string(r.native),
                                       "romanization": .opt(r.romanization), "back_translation": .opt(r.backTranslation),
                                       "on_server": .bool(session != nil)])
            }
            loading = false
        }
    }

    private func startWriting() {
        guard let r = result else { return }
        let phrase = session?.asPhrase ?? Phrase(id: "compose-local", text: r.native, chars: r.chars, romanization: r.romanization, meaning: r.backTranslation)
        let items = PracticeItem.all(lang: lang, phrase: phrase, adHoc: session == nil)
        if !items.isEmpty { launch = PracticeLaunch(items: items, mode: .compose, title: text) }
    }
}

struct LangPicker: View {
    @Environment(AppModel.self) private var app
    @Binding var selection: String

    var body: some View {
        ScrollViewReader { proxy in
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(app.lessons) { l in
                    Button { withAnimation(.snappy) { selection = l.lang } } label: {
                        VStack(spacing: 2) {
                            Text(ScriptInfo.hero(l.lang)).font(Theme.script(l.lang, size: 16)).lineLimit(1)
                            Text(l.name).font(Theme.sans(11, weight: .medium))
                        }
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .foregroundStyle(selection == l.lang ? .white : Theme.ink)
                        .background(selection == l.lang ? Theme.accent : Theme.card, in: RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.hairline, lineWidth: selection == l.lang ? 0 : 1))
                    }
                    .buttonStyle(PressableStyle())
                    .id(l.lang)
                }
            }
        }
        .onAppear { proxy.scrollTo(selection, anchor: .center) }
        .onChange(of: selection) { _, new in withAnimation(.snappy) { proxy.scrollTo(new, anchor: .center) } }
        }
    }
}

// MARK: Write your name

struct NameView: View {
    @Environment(AppModel.self) private var app
    @AppStorage("name") private var name = ""
    @State private var results: [NameResponse.Rendering] = []
    @State private var loading = false
    @State private var error: String?
    @State private var launch: PracticeLaunch?
    @State private var note: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Write your name").font(Theme.display(30, weight: .medium))
                Text("See it in every script, then write it by hand. Spellings are approximate: names are sounded out.")
                    .font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
                HStack {
                    TextField("Your name", text: $name)
                        .font(Theme.display(24))
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                        .submitLabel(.go)
                        .onSubmit(fetch)
                    Button(action: fetch) {
                        if loading { ProgressView() } else { Image(systemName: "arrow.right.circle.fill").font(.system(size: 30)) }
                    }
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                .card()
                if let error { Label(error, systemImage: "exclamationmark.triangle").font(Theme.sans(13)).foregroundStyle(Theme.warn) }
                if results.isEmpty && !loading && error == nil {
                    VStack(spacing: 8) {
                        Image(systemName: "signature").font(.system(size: 34)).foregroundStyle(Theme.accent.opacity(0.7))
                        Text("Your name in five scripts.").font(Theme.display(18)).foregroundStyle(Theme.inkSoft)
                    }
                    .frame(maxWidth: .infinity).padding(.vertical, 30)
                }
                ForEach(results) { r in
                    Button {
                        let phrase = Phrase(id: "name-\(r.lang)", text: r.text, chars: r.chars, romanization: r.romanization, meaning: name)
                        launch = PracticeLaunch(items: PracticeItem.all(lang: r.lang, phrase: phrase, adHoc: true), mode: .write, title: name, isName: true)
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(app.lesson(r.lang)?.name ?? r.lang.capitalized).font(Theme.sans(12, weight: .semibold)).foregroundStyle(Theme.inkSoft)
                                Text(r.text).font(Theme.script(r.lang, size: 34)).foregroundStyle(Theme.ink)
                                    .environment(\.layoutDirection, ScriptInfo.isRTL(r.lang) ? .rightToLeft : .leftToRight)
                                if let rom = r.romanization { Text(rom).font(Theme.sans(14, weight: .medium)).foregroundStyle(Theme.accent) }
                                if r.offline {
                                    HStack(spacing: 6) {
                                        if loading { ProgressView().controlSize(.mini) }
                                        Text(loading ? "Quick spelling · checking with the tutor…" : "Spelled by sound (approximate)")
                                    }
                                    .font(Theme.sans(11)).foregroundStyle(Theme.inkSoft)
                                }
                            }
                            Spacer()
                            Image(systemName: "pencil.and.scribble").foregroundStyle(Theme.accent)
                        }
                        .card()
                    }
                    .buttonStyle(PressableStyle())
                    .disabled(r.chars.isEmpty)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .padding(18)
            .animation(.spring(response: 0.5, dampingFraction: 0.85), value: results)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $launch) { PracticeView(launch: $0) }
        .onAppear { if !name.isEmpty && results.isEmpty { fetch() } }
    }

    private func show(_ list: [NameResponse.Rendering]) {
        results = list.filter { ScriptInfo.order.contains($0.lang) && !$0.text.isEmpty }
            .sorted { (ScriptInfo.order.firstIndex(of: $0.lang) ?? 99) < (ScriptInfo.order.firstIndex(of: $1.lang) ?? 99) }
    }

    private func fetch() {
        let n = name.trimmingCharacters(in: .whitespaces)
        guard !n.isEmpty, let api = app.api else { return }
        loading = true; error = nil
        Task {
            // Instant: spell it on the phone with the team's sound tables, then swap in the server's spelling
            // (a language model, 5–8 s) when it answers. One quiet retry; the offline version stays if both fail.
            show(app.offlineName(n))
            var server: [NameResponse.Rendering]?
            for attempt in 0..<2 where server == nil {
                if attempt > 0 { try? await Task.sleep(for: .milliseconds(600)) }
                server = try? await api.name(n).results
            }
            guard name.trimmingCharacters(in: .whitespaces) == n else { return }
            if let server, !server.isEmpty { show(server) } else if results.isEmpty { error = "Couldn't spell that right now." }
            app.report("name", ["name": .string(n), "scripts": .int(results.count), "offline": .bool(results.first?.offline ?? false)])
            loading = false
        }
    }
}

// MARK: Daily 5

struct DailyView: View {
    @Environment(AppModel.self) private var app
    @State private var items: [PracticeItem] = []
    @State private var reasons: [String: String] = [:]
    @State private var loading = true
    @State private var launch: PracticeLaunch?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Daily 5").font(Theme.display(30, weight: .medium))
                Text("Five characters picked for today: shaky ones, ones you haven't seen in a while, and something new.")
                    .font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
                if loading {
                    ProgressView().frame(maxWidth: .infinity).padding(40)
                } else if items.isEmpty {
                    ContentUnavailableView("Nothing to review yet", systemImage: "sparkles",
                                           description: Text("Practice a language first; Daily 5 picks from what you've written."))
                } else {
                    ForEach(items) { it in
                        HStack(spacing: 14) {
                            Text(it.char).font(Theme.script(it.lang, size: 38)).frame(width: 64)
                                .lineLimit(1).minimumScaleFactor(0.4)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(it.phrase.meaning ?? it.phrase.text).font(Theme.display(17))
                                Text(app.lesson(it.lang)?.name ?? it.lang).font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
                                if let why = reasons[it.id] { Text(why).font(Theme.sans(12, weight: .medium)).foregroundStyle(Theme.accent) }
                            }
                            Spacer()
                            LevelDot(level: app.progress.progress(it.lang, it.char).level)
                        }
                        .card(padding: 12)
                    }
                    Button { launch = PracticeLaunch(items: items, mode: .write, title: "Daily 5") } label: {
                        Label("Start Daily 5", systemImage: "play.fill")
                    }
                    .buttonStyle(PrimaryButtonStyle())
                }
            }
            .padding(18)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $launch) { PracticeView(launch: $0) }
        .task { await load() }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        var out: [PracticeItem] = []
        var why: [String: String] = [:]
        if let api = app.api, let r = try? await api.review() {
            for it in r.items {
                guard let lesson = app.lesson(it.lang), let phrase = lesson.phrases.first(where: { $0.id == it.item }) else { continue }
                let idx = min(max(0, it.charIndex ?? 0), max(0, phrase.chars.count - 1))
                guard phrase.chars.indices.contains(idx) else { continue }
                let p = PracticeItem(lang: it.lang, phrase: phrase, charIndex: idx, adHoc: false)
                out.append(p)
                if let reason = it.reason { why[p.id] = reason }
            }
        }
        if out.count < 5 { out += localPicks(excluding: Set(out.map(\.id)), count: 5 - out.count, reasons: &why) }
        items = Array(out.prefix(5))
        reasons = why
        app.report("daily.loaded", ["count": .int(items.count)])
    }

    /// On-device fallback: weakest practiced chars first, then unseen ones.
    private func localPicks(excluding: Set<String>, count: Int, reasons: inout [String: String]) -> [PracticeItem] {
        let all = app.lessons.flatMap { l in l.phrases.flatMap { PracticeItem.all(lang: l.lang, phrase: $0) } }
            .filter { !excluding.contains($0.id) }
        var seenChars = Set<String>()
        let unique = all.filter { seenChars.insert("\($0.lang)/\($0.char)").inserted }
        let scored = unique.map { it -> (PracticeItem, Int, String) in
            let p = app.progress.progress(it.lang, it.char)
            switch p.level {
            case .practiced where p.lastCorrect == false: return (it, 0, "shaky last time")
            case .practiced: return (it, 1, "almost mastered")
            case .seen: return (it, 2, "seen, not written yet")
            case .new: return (it, 3, "new today")
            case .mastered: return (it, 4, "keep it fresh")
            }
        }
        .sorted { $0.1 < $1.1 }
        let picks = scored.prefix(count)
        for p in picks { reasons[p.0.id] = p.2 }
        return picks.map(\.0)
    }
}

// MARK: Journal

struct JournalView: View {
    @Environment(AppModel.self) private var app
    let lang: String
    @State private var entries: [JournalResponse.Entry] = []
    @State private var loading = true
    @State private var failed = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Journal").font(Theme.display(30, weight: .medium))
                Text("Every page you've written, so you can watch your hand improve.").font(Theme.sans(14)).foregroundStyle(Theme.inkSoft)
                if loading {
                    ProgressView().frame(maxWidth: .infinity).padding(40)
                } else if entries.isEmpty {
                    ContentUnavailableView(failed ? "Journal unavailable" : "No pages yet", systemImage: "book.pages",
                                           description: Text(failed ? "The lesson server didn't answer." : "Write a character and its photo lands here."))
                } else {
                    ForEach(entries) { e in
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Text(e.char).font(Theme.script(lang, size: 32))
                                Spacer()
                                Text("\(e.photos.count) \(e.photos.count == 1 ? "page" : "pages")").font(Theme.sans(12)).foregroundStyle(Theme.inkSoft)
                                if let best = e.best {
                                    Text("best \(Int(best))").font(Theme.sans(12, weight: .semibold)).foregroundStyle(Theme.good)
                                }
                            }
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 10) {
                                    ForEach(e.photos) { p in JournalPhoto(photo: p) }
                                }
                            }
                        }
                        .card()
                    }
                }
            }
            .padding(18)
        }
        .background(Theme.paper.ignoresSafeArea())
        .navigationTitle(app.lesson(lang)?.name ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            loading = true
            if let api = app.api {
                do { entries = try await api.journal(lang: lang).entries } catch { failed = true }
            }
            loading = false
        }
    }
}

private struct JournalPhoto: View {
    @Environment(AppModel.self) private var app
    let photo: JournalResponse.Photo

    var body: some View {
        VStack(spacing: 4) {
            AsyncImage(url: app.api?.url(photo.url)) { phase in
                switch phase {
                case .success(let img): img.resizable().scaledToFill()
                case .failure: Image(systemName: "photo").foregroundStyle(Theme.inkSoft)
                default: ProgressView()
                }
            }
            .frame(width: 110, height: 110)
            .background(Theme.paper)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            HStack(spacing: 4) {
                Text(Date(timeIntervalSince1970: photo.ts), format: .dateTime.month(.abbreviated).day())
                if let s = photo.score { Text("· \(Int(s))").foregroundStyle(photo.correct ?? (s >= 60) ? Theme.good : Theme.warn) }
            }
            .font(Theme.sans(11, weight: .medium)).foregroundStyle(Theme.inkSoft)
        }
    }
}
