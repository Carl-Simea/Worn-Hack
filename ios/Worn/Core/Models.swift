import Foundation

// Shapes follow the live backend (backend/app.py, checked against real responses), the content files
// (content/*.json) and web/dev/mock_server.py. Decoding is tolerant: optional fields stay optional and both
// spellings the team uses (`phrase_id` / `item_id`, `phrases` / `items`, `text` / `native`) are accepted.
// All network decoding uses .convertFromSnakeCase.

struct ContentResponse: Decodable {
    let langs: [Lesson]
}

struct Lesson: Decodable, Identifiable, Hashable {
    let lang: String
    let name: String
    let script: String?
    let scriptType: String?
    let rtl: Bool?
    let about: String?
    let hero: String?
    let strokeOrder: String?
    let strokeSource: String?
    var phrases: [Phrase]

    enum CodingKeys: String, CodingKey { case lang, name, script, scriptType, rtl, about, hero, strokeOrder, strokeSource, phrases, items }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        lang = try c.decode(String.self, forKey: .lang)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? lang.capitalized
        script = try c.decodeIfPresent(String.self, forKey: .script)
        scriptType = try c.decodeIfPresent(String.self, forKey: .scriptType)
        rtl = try c.decodeIfPresent(Bool.self, forKey: .rtl)
        about = try c.decodeIfPresent(String.self, forKey: .about)
        hero = try c.decodeIfPresent(String.self, forKey: .hero)
        strokeOrder = try c.decodeIfPresent(String.self, forKey: .strokeOrder)
        strokeSource = try c.decodeIfPresent(String.self, forKey: .strokeSource)
        phrases = try c.decodeIfPresent([Phrase].self, forKey: .items) ?? c.decodeIfPresent([Phrase].self, forKey: .phrases) ?? []
    }

    var id: String { lang }
    var isRTL: Bool { rtl ?? ScriptInfo.isRTL(lang) }
}

struct Phrase: Decodable, Identifiable, Hashable {
    struct CharInfo: Decodable, Hashable {
        let char: String
        let strokeCount: Int?
        let strokeUrl: String?
    }

    let id: String
    let text: String
    let chars: [String]
    let romanization: String?
    let meaning: String?
    let audio: String?
    let how: String?
    let why: String?
    let dictation: String?
    let charRomanization: [String]?
    let charInfo: [CharInfo]?

    enum CodingKeys: String, CodingKey {
        case id, itemId, phraseId, text, chars, romanization, meaning, audio, audioUrl, how, why, dictation, charRomanization, charInfo
    }

    init(id: String, text: String, chars: [String], romanization: String?, meaning: String?,
         audio: String? = nil, how: String? = nil, why: String? = nil, dictation: String? = nil) {
        self.id = id; self.text = text; self.chars = chars; self.romanization = romanization
        self.meaning = meaning; self.audio = audio; self.how = how; self.why = why; self.dictation = dictation
        charRomanization = nil; charInfo = nil
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id)
            ?? c.decodeIfPresent(String.self, forKey: .itemId)
            ?? c.decode(String.self, forKey: .phraseId)
        text = try c.decode(String.self, forKey: .text)
        chars = try c.decodeIfPresent([String].self, forKey: .chars) ?? []
        romanization = try c.decodeIfPresent(String.self, forKey: .romanization)
        meaning = try c.decodeIfPresent(String.self, forKey: .meaning)
        // The backend sends a ready-to-use `audio_url`; raw content files only have `audio`.
        audio = try c.decodeIfPresent(String.self, forKey: .audioUrl) ?? c.decodeIfPresent(String.self, forKey: .audio)
        how = try c.decodeIfPresent(String.self, forKey: .how)
        why = try c.decodeIfPresent(String.self, forKey: .why)
        dictation = try c.decodeIfPresent(String.self, forKey: .dictation)
        charRomanization = try? c.decodeIfPresent([String].self, forKey: .charRomanization)
        charInfo = try? c.decodeIfPresent([CharInfo].self, forKey: .charInfo)
    }

    var canWrite: Bool { !chars.isEmpty }

    func romanization(at i: Int) -> String? {
        guard let r = charRomanization, r.count == chars.count, r.indices.contains(i) else { return nil }
        return r[i]
    }

    func strokeURL(at i: Int) -> String? {
        guard let info = charInfo, info.indices.contains(i), info[i].char == chars[i] else { return nil }
        return info[i].strokeUrl
    }
}

enum PracticeMode: String, Codable, CaseIterable, Sendable {
    case write, dictation, compose
}

/// POST /session. `item_id` is the contract name; `phrase_id` is still accepted and sent for older servers.
/// Compose: send `text` (the learner's English message) with mode "compose" and no id; the server translates
/// it, stores the item, and answers with its `item_id` for the following characters.
struct SessionRequest: Encodable {
    let lang: String
    let itemId: String?
    let phraseId: String?
    let charIndex: Int
    let mode: PracticeMode
    let text: String?

    init(lang: String, itemId: String, charIndex: Int, mode: PracticeMode) {
        self.lang = lang; self.itemId = itemId; phraseId = itemId; self.charIndex = charIndex
        self.mode = mode == .compose ? .compose : mode; text = nil
    }

    init(composing text: String, lang: String) {
        self.lang = lang; itemId = nil; phraseId = nil; charIndex = 0; mode = .compose; self.text = text
    }
}

struct SessionState: Decodable, Equatable {
    struct Item: Decodable, Equatable {
        let id: String
        let text: String?
        let chars: [String]?
        let romanization: String?
        let meaning: String?
    }

    let lang: String
    let langName: String?
    let rtl: Bool?
    let itemId: String?
    let phraseId: String?
    let item: Item?
    let text: String?
    let char: String?
    let charIndex: Int
    let totalChars: Int?
    let romanization: String?
    let meaning: String?
    let audioUrl: String?
    let strokeUrl: String?
    let strokeCount: Int?
    /// "true" (real order), "suggested" (hand-authored), "trace" (no order).
    let strokeOrder: String?
    let mode: String?
    let backTranslation: String?
    let note: String?
    let version: Int?

    var id: String { itemId ?? phraseId ?? item?.id ?? "" }

    /// The item as a phrase (used for compose items the phone didn't have before).
    var asPhrase: Phrase? {
        guard let chars = item?.chars ?? (totalChars == 1 ? char.map { [$0] } : nil), !chars.isEmpty else { return nil }
        return Phrase(id: id, text: item?.text ?? text ?? chars.joined(), chars: chars,
                      romanization: item?.romanization ?? romanization, meaning: item?.meaning ?? meaning, audio: audioUrl)
    }
}

struct GradeResult: Decodable, Equatable {
    struct Next: Decodable, Equatable {
        let lang: String?
        let itemId: String?
        let charIndex: Int?
        let action: String?
        let reason: String?
    }

    let correct: Bool
    /// nil when the checker found no writing in the photo (status "no_writing").
    let score: Double?
    let feedback: String
    /// "ok" or "no_writing".
    let status: String?
    /// recognizable, proportions, placement, completeness, neatness (0-100 each).
    let subscores: [String: Double]?
    let weakest: String?
    /// The part of the photo the checker actually looked at.
    let cropUrl: String?
    /// Shape-only score against the model letter, and what the rubric read the writing as.
    let templateScore: Double?
    /// The tutor agent's spoken line ("Great job! Keep going.").
    let reaction: String?
    let mood: String?
    let sound: String?
    let seen: String?
    let char: String?
    let lang: String?
    let imageUrl: String?
    let next: Next?
    let ts: Double?
    let latencyMs: Double?

    var scoreInt: Int { Int((score ?? 0).rounded()) }
    var noWriting: Bool { status == "no_writing" || score == nil }
    /// The agent wants another try at this character.
    var wantsRetry: Bool { next?.action == "retry" }

    init(correct: Bool, score: Double, feedback: String, reaction: String? = nil, seen: String? = nil) {
        self.correct = correct; self.score = score; self.feedback = feedback; self.reaction = reaction; self.seen = seen
        status = nil; subscores = nil; weakest = nil; cropUrl = nil; templateScore = nil
        mood = nil; sound = nil; char = nil; lang = nil; imageUrl = nil; next = nil; ts = nil; latencyMs = nil
    }
}

struct StrokeMatch: Decodable, Equatable {
    let score: Double
    let done: Bool
    let strokeIndex: Int?
    let strokeCount: Int?
    let charDone: Bool?
    let ink: Bool?
    let hint: String?
    let latencyMs: Double?
}

/// POST /compose: {native, romanization, back_translation, chars[], note, text}. The mock's
/// {text, chars, romanization, meaning} also decodes.
struct ComposeResult: Decodable, Equatable {
    let native: String
    let romanization: String?
    let backTranslation: String?
    let chars: [String]
    let note: String?

    enum CodingKeys: String, CodingKey { case native, text, romanization, backTranslation, meaning, chars, note }

    init(native: String, romanization: String?, backTranslation: String?, chars: [String], note: String?) {
        self.native = native; self.romanization = romanization; self.backTranslation = backTranslation
        self.chars = chars; self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        native = try c.decodeIfPresent(String.self, forKey: .native) ?? c.decode(String.self, forKey: .text)
        romanization = try c.decodeIfPresent(String.self, forKey: .romanization)
        backTranslation = try c.decodeIfPresent(String.self, forKey: .backTranslation) ?? c.decodeIfPresent(String.self, forKey: .meaning)
        let decoded = try c.decodeIfPresent([String].self, forKey: .chars) ?? []
        chars = decoded.isEmpty ? native.map(String.init).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } : decoded
        note = try c.decodeIfPresent(String.self, forKey: .note)
    }

    init(session s: SessionState) {
        native = s.item?.text ?? s.text ?? ""
        romanization = s.item?.romanization ?? s.romanization
        backTranslation = s.backTranslation ?? s.item?.meaning ?? s.meaning
        chars = s.item?.chars ?? []
        note = s.note
    }
}

/// GET /name?text=. Live backend: {devanagari, arabic, cyrillic, hebrew, greek, text, note}.
/// Mock: {name, results: [{lang, text, chars, romanization}]}. Both decode into `results`.
struct NameResponse: Decodable {
    struct Rendering: Decodable, Identifiable, Hashable {
        let lang: String
        let text: String
        let chars: [String]
        let romanization: String?
        var offline = false
        var id: String { lang }

        enum CodingKeys: String, CodingKey { case lang, text, chars, romanization }

        init(lang: String, text: String, chars: [String]? = nil, romanization: String? = nil, offline: Bool = false) {
            self.lang = lang; self.text = text; self.romanization = romanization; self.offline = offline
            self.chars = chars ?? NameResponse.split(text)
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            lang = try c.decode(String.self, forKey: .lang)
            text = try c.decode(String.self, forKey: .text)
            chars = try c.decodeIfPresent([String].self, forKey: .chars) ?? NameResponse.split(text)
            romanization = try c.decodeIfPresent(String.self, forKey: .romanization)
        }
    }

    static let scriptKeys: [(key: String, lang: String)] = [
        ("devanagari", "hindi"), ("arabic", "arabic"), ("cyrillic", "russian"), ("hebrew", "hebrew"), ("greek", "greek"),
    ]

    let name: String?
    let note: String?
    var results: [Rendering]

    init(name: String?, note: String?, results: [Rendering]) { self.name = name; self.note = note; self.results = results }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        note = try c.decodeIfPresent(String.self, forKey: AnyKey("note"))
        if let list = try? c.decode([Rendering].self, forKey: AnyKey("results")) {
            name = try c.decodeIfPresent(String.self, forKey: AnyKey("name"))
            results = list
        } else {
            name = try c.decodeIfPresent(String.self, forKey: AnyKey("text"))
            results = Self.scriptKeys.compactMap { k in
                (try? c.decodeIfPresent(String.self, forKey: AnyKey(k.key))).flatMap { $0 }.map { Rendering(lang: k.lang, text: $0) }
            }
        }
    }

    /// Writable units: grapheme clusters (keeps Devanagari conjuncts and marks together), no spaces.
    static func split(_ s: String) -> [String] {
        s.map(String.init).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0 != "'" }
    }
}

/// GET /journal?lang=. Live backend: flat attempts {lang, char, score, correct, image_url, ts, item_id}.
/// Mock: grouped {char, photos: [{url, ts, score, day}]}. Both end up grouped per character.
struct JournalResponse: Decodable {
    struct Photo: Hashable, Identifiable {
        let url: String
        let ts: Double
        let score: Double?
        let correct: Bool?
        var id: String { url + "\(ts)" }
    }
    struct Entry: Hashable, Identifiable {
        let char: String
        var photos: [Photo]
        var id: String { char }
        var best: Double? { photos.compactMap(\.score).max() }
    }

    let entries: [Entry]

    private struct Row: Decodable {
        let char: String
        let score: Double?
        let correct: Bool?
        let imageUrl: String?
        let ts: Double?
        let photos: [MockPhoto]?
    }
    private struct MockPhoto: Decodable { let url: String; let ts: Double; let score: Double? }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        let rows = try c.decodeIfPresent([Row].self, forKey: AnyKey("entries")) ?? []
        var order: [String] = []
        var map: [String: Entry] = [:]
        for r in rows {
            var photos: [Photo] = (r.photos ?? []).map { Photo(url: $0.url, ts: $0.ts, score: $0.score, correct: nil) }
            if let u = r.imageUrl { photos.append(Photo(url: u, ts: r.ts ?? 0, score: r.score, correct: r.correct)) }
            if map[r.char] == nil { order.append(r.char); map[r.char] = Entry(char: r.char, photos: []) }
            map[r.char]?.photos += photos
        }
        // Oldest first within a character, so the strip reads as progress.
        entries = order.compactMap { k in map[k].map { Entry(char: $0.char, photos: $0.photos.sorted { $0.ts < $1.ts }) } }
    }
}

/// GET /review
struct ReviewResponse: Decodable {
    struct Item: Decodable, Hashable, Identifiable {
        let lang: String
        let phraseId: String?
        let itemId: String?
        let charIndex: Int?
        let char: String?
        let reason: String?
        var id: String { "\(lang)/\(item)/\(charIndex ?? 0)" }
        var item: String { itemId ?? phraseId ?? "" }
    }
    let items: [Item]
    let message: String?
}

struct Health: Decodable {
    let ok: Bool
    let modelReady: Bool?
    let fakeGrade: Bool?
    let mock: Bool?
}

/// POST /event body. `data` is free-form JSON; /live/state mirrors it.
struct EventBody: Encodable {
    let type: String
    let data: [String: JSONValue]
}

/// Minimal JSON value for event payloads.
enum JSONValue: Encodable, Equatable, Sendable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        case .null: try c.encodeNil()
        }
    }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral, ExpressibleByBooleanLiteral {
    init(stringLiteral value: String) { self = .string(value) }
    init(integerLiteral value: Int) { self = .number(Double(value)) }
    init(floatLiteral value: Double) { self = .number(value) }
    init(booleanLiteral value: Bool) { self = .bool(value) }
    static func int(_ v: Int) -> JSONValue { .number(Double(v)) }
    static func opt(_ s: String?) -> JSONValue { s.map(JSONValue.string) ?? .null }
}

// MARK: content/reactions.json

/// {correct|close|wrong|streak|milestone: {sound, alt_sounds, then, at, lines}}. Sounds are content/sfx/NAME.wav.
struct Reactions: Decodable {
    struct Kind: Decodable {
        let sound: String?
        let altSounds: [String]?
        let then: String?
        let at: [Int]?
        let lines: [String]

        enum CodingKeys: String, CodingKey { case sound, altSounds = "alt_sounds", then, at, lines }
    }
    var kinds: [String: Kind]

    init(kinds: [String: Kind]) { self.kinds = kinds }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        var out: [String: Kind] = [:]
        for k in c.allKeys where !k.stringValue.hasPrefix("_") {
            if let kind = try? c.decode(Kind.self, forKey: k) { out[k.stringValue] = kind }
        }
        kinds = out
    }

    /// "correct" / "close" (wrong, score ≥ 50) / "wrong".
    static func key(correct: Bool, score: Int) -> String { correct ? "correct" : (score >= 50 ? "close" : "wrong") }

    func line(_ key: String, n: Int? = nil) -> String? {
        guard var l = kinds[key]?.lines.randomElement() else { return nil }
        if let n { l = l.replacingOccurrences(of: "{n}", with: String(n)) }
        return l
    }

    func sounds(_ key: String) -> [String] {
        guard let k = kinds[key] else { return [] }
        let first = ([k.sound].compactMap { $0 } + (k.altSounds ?? [])).randomElement()
        return [first, k.then].compactMap { $0 }
    }

    func isStreak(_ n: Int) -> Bool { (kinds["streak"]?.at ?? [3, 5, 10]).contains(n) }

    static let fallback = Reactions(kinds: [
        "correct": Kind(sound: "ding", altSounds: nil, then: nil, at: nil, lines: ["Chef's kiss!", "Nailed it!", "Your pen knows what it's doing."]),
        "close": Kind(sound: "boing", altSounds: nil, then: nil, at: nil, lines: ["Ohhh, so close!", "Almost! One tiny fix."]),
        "wrong": Kind(sound: "buzzer", altSounds: nil, then: nil, at: nil, lines: ["Bold. Wrong, but bold.", "Plot twist: try again."]),
        "streak": Kind(sound: "drumroll", altSounds: nil, then: "cheer", at: [3, 5, 10], lines: ["{n} in a row!"]),
        "milestone": Kind(sound: "tada", altSounds: nil, then: "sparkle", at: nil, lines: ["New skill unlocked!"]),
    ])
}

// MARK: content/milestones.json

/// {lang: {first_letter|first_word|first_mastered: {spoken, shown}}, any: {first_name, all_six_languages}}
struct Milestones: Decodable {
    struct Line: Decodable, Hashable {
        let spoken: String
        let shown: String?
    }
    var byLang: [String: [String: Line]]

    init(byLang: [String: [String: Line]]) { self.byLang = byLang }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        var out: [String: [String: Line]] = [:]
        for k in c.allKeys where !k.stringValue.hasPrefix("_") {
            if let m = try? c.decode([String: Line].self, forKey: k) { out[k.stringValue] = m }
        }
        byLang = out
    }

    func line(_ lang: String, _ id: String) -> Line? { byLang[lang]?[id] ?? byLang["any"]?[id] }

    static let fallback = Milestones(byLang: [
        "any": [
            "first_letter": Line(spoken: "Your first letter in a new script. Nice!", shown: "First letter ✓"),
            "first_word": Line(spoken: "Your first whole word!", shown: "First word ✓"),
            "first_mastered": Line(spoken: "Mastered! That one's yours for keeps.", shown: "Mastered ✓"),
            "first_name": Line(spoken: "You just wrote your name in a new script. Certified scribe!", shown: "Your name ✓"),
            "all_six_languages": Line(spoken: "Six scripts in one sitting. That's a world tour!", shown: "6 scripts ✓"),
        ],
    ])
}

/// A milestone that just fired.
struct EarnedMilestone: Equatable, Identifiable {
    let id: String       // "hebrew/first_letter"
    let line: Milestones.Line
}

// MARK: content/names/*.json (offline fallback for "Write your name")

struct NameTable: Decodable {
    let script: String?
    let lang: String
    let rtl: Bool?
    let note: String?
    let sounds: [String: String]

    /// Spell an English name by sound with this table (see NameSpeller). Approximate by design.
    func spell(_ name: String) -> String { NameSpeller.spell(name, table: self) }
}

struct AnyKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(_ s: String) { stringValue = s }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}
