import Foundation

// Shapes follow the backend contract (backend/app.py), the content files (content/{lang}.json) and
// web/dev/mock_server.py. Decoding is deliberately tolerant: optional fields stay optional and the
// two spellings the team uses (`phrase_id` / `item_id`, `text` / `native`) are both accepted.
// All decoding uses .convertFromSnakeCase.

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
    let strokeOrder: String?
    let strokeSource: String?
    var phrases: [Phrase]

    var id: String { lang }
    var isRTL: Bool { rtl ?? false }
    /// Only Mandarin and Japanese carry true stroke order; the rest are traced shapes.
    var hasTrueStrokeOrder: Bool { strokeOrder == "standard" }
}

struct Phrase: Decodable, Identifiable, Hashable {
    let id: String
    let text: String
    let chars: [String]
    let romanization: String?
    let meaning: String?
    let audio: String?
    let how: String?
    let why: String?
    let dictation: String?

    enum CodingKeys: String, CodingKey { case id, itemId, phraseId, text, chars, romanization, meaning, audio, how, why, dictation }

    init(id: String, text: String, chars: [String], romanization: String?, meaning: String?,
         audio: String? = nil, how: String? = nil, why: String? = nil, dictation: String? = nil) {
        self.id = id; self.text = text; self.chars = chars; self.romanization = romanization
        self.meaning = meaning; self.audio = audio; self.how = how; self.why = why; self.dictation = dictation
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
        audio = try c.decodeIfPresent(String.self, forKey: .audio)
        how = try c.decodeIfPresent(String.self, forKey: .how)
        why = try c.decodeIfPresent(String.self, forKey: .why)
        dictation = try c.decodeIfPresent(String.self, forKey: .dictation)
    }

    var canWrite: Bool { !chars.isEmpty }
}

enum PracticeMode: String, Codable, CaseIterable, Sendable {
    case write, dictation, compose
}

/// POST /session. Sends both `phrase_id` (current backend + mock) and `item_id` (new contract).
struct SessionRequest: Encodable {
    let lang: String
    let phraseId: String
    let itemId: String
    let charIndex: Int
    let mode: PracticeMode
    /// Free-form items (compose / name) the backend can't look up by id.
    let text: String?
    let chars: [String]?
    let romanization: String?
    let meaning: String?

    init(lang: String, item: Phrase, charIndex: Int, mode: PracticeMode, adHoc: Bool) {
        self.lang = lang
        phraseId = item.id
        itemId = item.id
        self.charIndex = charIndex
        self.mode = mode
        text = adHoc ? item.text : nil
        chars = adHoc ? item.chars : nil
        romanization = adHoc ? item.romanization : nil
        meaning = adHoc ? item.meaning : nil
    }
}

struct SessionState: Decodable, Equatable {
    let lang: String
    let langName: String?
    let rtl: Bool?
    let phraseId: String?
    let itemId: String?
    let text: String?
    let char: String?
    let charIndex: Int
    let totalChars: Int?
    let romanization: String?
    let meaning: String?
    let audioUrl: String?
    let strokeUrl: String?
    let mode: String?
    let version: Int?

    var id: String { itemId ?? phraseId ?? "" }
}

struct GradeResult: Decodable, Equatable {
    let correct: Bool
    let score: Double
    let feedback: String
    /// Short reaction key from the grader (e.g. "cheer"); maps into reactions.json.
    let reaction: String?
    let seen: String?
    let char: String?
    let lang: String?
    let ts: Double?
    let latencyMs: Double?

    var scoreInt: Int { Int(score.rounded()) }

    init(correct: Bool, score: Double, feedback: String, reaction: String? = nil, seen: String? = nil,
         char: String? = nil, lang: String? = nil, ts: Double? = nil, latencyMs: Double? = nil) {
        self.correct = correct; self.score = score; self.feedback = feedback; self.reaction = reaction
        self.seen = seen; self.char = char; self.lang = lang; self.ts = ts; self.latencyMs = latencyMs
    }
}

struct StrokeMatch: Decodable, Equatable {
    let score: Double
    let done: Bool
}

/// POST /compose. Contract: {native, romanization, back_translation, chars[], note};
/// the mock answers {text, chars, romanization, meaning, note}. Both decode.
struct ComposeResult: Decodable, Equatable {
    let native: String
    let romanization: String?
    let backTranslation: String?
    let chars: [String]
    let note: String?
    let lang: String?
    let phraseId: String?

    enum CodingKeys: String, CodingKey { case native, text, romanization, backTranslation, meaning, chars, note, lang, phraseId }

    init(native: String, romanization: String?, backTranslation: String?, chars: [String], note: String?,
         lang: String? = nil, phraseId: String? = nil) {
        self.native = native; self.romanization = romanization; self.backTranslation = backTranslation
        self.chars = chars; self.note = note; self.lang = lang; self.phraseId = phraseId
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        native = try c.decodeIfPresent(String.self, forKey: .native) ?? c.decode(String.self, forKey: .text)
        romanization = try c.decodeIfPresent(String.self, forKey: .romanization)
        backTranslation = try c.decodeIfPresent(String.self, forKey: .backTranslation)
            ?? c.decodeIfPresent(String.self, forKey: .meaning)
        let decodedChars = try c.decodeIfPresent([String].self, forKey: .chars) ?? []
        chars = decodedChars.isEmpty ? native.map(String.init).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } : decodedChars
        note = try c.decodeIfPresent(String.self, forKey: .note)
        lang = try c.decodeIfPresent(String.self, forKey: .lang)
        phraseId = try c.decodeIfPresent(String.self, forKey: .phraseId)
    }

    func asPhrase(id: String) -> Phrase {
        Phrase(id: phraseId ?? id, text: native, chars: chars, romanization: romanization, meaning: backTranslation)
    }
}

/// GET /name?text=
struct NameResponse: Decodable {
    struct Rendering: Decodable, Identifiable, Hashable {
        let lang: String
        let text: String
        let chars: [String]
        let romanization: String?
        var id: String { lang }
    }
    let name: String?
    let results: [Rendering]
}

/// GET /journal?lang=
struct JournalResponse: Decodable {
    struct Photo: Decodable, Hashable, Identifiable {
        let url: String
        let ts: Double
        let score: Double?
        let day: Int?
        var id: String { url + "\(ts)" }
    }
    struct Entry: Decodable, Hashable, Identifiable {
        let char: String
        let phraseId: String?
        let photos: [Photo]
        var id: String { char + (phraseId ?? "") }
    }
    let lang: String?
    let entries: [Entry]
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
        var id: String { "\(lang)/\(itemId ?? phraseId ?? "")/\(charIndex ?? 0)" }
        var item: String { itemId ?? phraseId ?? "" }
    }
    let items: [Item]
    let date: String?
}

struct Health: Decodable {
    let ok: Bool
    let modelReady: Bool?
    let fakeGrade: Bool?
    let mock: Bool?
}

/// POST /event body. `data` is free-form JSON so the judge site can mirror everything.
struct EventBody: Encodable {
    let type: String
    let data: [String: JSONValue]
    let ts: Double
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

// MARK: content/reactions.json and content/milestones.json (optional files; bundled defaults below)

struct Reactions: Decodable {
    /// key -> lines. Keys used: "correct", "close", "wrong", "blank", "streak", plus any grader `reaction`.
    let lines: [String: [String]]
    /// key -> sound name ("chime", "pop", "boing", "tada") played on the phone.
    let sounds: [String: String]?

    init(lines: [String: [String]], sounds: [String: String]? = nil) { self.lines = lines; self.sounds = sounds }

    init(from decoder: Decoder) throws {
        // Accept either {"lines": {...}, "sounds": {...}} or a flat {"correct": [...], ...}.
        if let keyed = try? decoder.container(keyedBy: AnyKey.self), keyed.contains(AnyKey("lines")) {
            lines = try keyed.decode([String: [String]].self, forKey: AnyKey("lines"))
            sounds = try keyed.decodeIfPresent([String: String].self, forKey: AnyKey("sounds"))
        } else {
            lines = try decoder.singleValueContainer().decode([String: [String]].self)
            sounds = nil
        }
    }

    func line(for key: String) -> String? { lines[key]?.randomElement() }

    static let fallback = Reactions(lines: [
        "correct": ["Chef's kiss.", "Your hand knows it now.", "Calligrapher energy.", "That's the one.", "Ink-credible."],
        "close": ["So close it squeaked.", "Almost! One stroke is wandering.", "Recognizable. Now make it proud."],
        "wrong": ["Bold. Wrong, but bold.", "That's a lovely different character.", "Plot twist: try again."],
        "blank": ["Is the pen on strike?", "I see paper. Very nice paper.", "Hold the page a little closer."],
        "dictation_correct": ["From memory! Show-off.", "No peeking and still perfect."],
        "dictation_wrong": ["Memory took a coffee break.", "Your hand improvised. Let's look again."],
    ], sounds: ["correct": "tada", "close": "pop", "wrong": "boing", "blank": "boing"])
}

struct Milestones: Decodable {
    struct Milestone: Decodable, Hashable {
        let id: String
        let title: String
        let detail: String?
        /// "chars_mastered", "streak_days", "first_correct", "lang_complete", "perfect_score"
        let kind: String
        let count: Int?
    }
    let milestones: [Milestone]

    init(milestones: [Milestone]) { self.milestones = milestones }

    init(from decoder: Decoder) throws {
        if let list = try? decoder.singleValueContainer().decode([Milestone].self) {
            milestones = list
        } else {
            let c = try decoder.container(keyedBy: AnyKey.self)
            milestones = try c.decode([Milestone].self, forKey: AnyKey("milestones"))
        }
    }

    static let fallback = Milestones(milestones: [
        .init(id: "first_correct", title: "First mark", detail: "Your first character, written by hand.", kind: "first_correct", count: 1),
        .init(id: "five_mastered", title: "Five down", detail: "Five characters mastered.", kind: "chars_mastered", count: 5),
        .init(id: "perfect", title: "Flawless", detail: "A perfect 100.", kind: "perfect_score", count: 100),
        .init(id: "lang_complete", title: "Whole script", detail: "Every item in a language practiced.", kind: "lang_complete", count: nil),
        .init(id: "streak_3", title: "Three-day streak", detail: "Three days in a row.", kind: "streak_days", count: 3),
    ])
}

struct AnyKey: CodingKey {
    let stringValue: String
    var intValue: Int? { nil }
    init(_ s: String) { stringValue = s }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { nil }
}
