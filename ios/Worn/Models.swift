import Foundation

// Shapes match backend/app.py and content/{lang}.json. Decoded with .convertFromSnakeCase.

struct ContentResponse: Decodable {
    let langs: [Lesson]
}

struct Lesson: Decodable, Identifiable, Hashable {
    let lang: String
    let name: String
    let rtl: Bool?
    let phrases: [Phrase]

    var id: String { lang }
    var isRTL: Bool { rtl ?? false }
}

struct Phrase: Decodable, Identifiable, Hashable {
    let id: String
    let text: String
    let chars: [String]
    let romanization: String?
    let meaning: String?
    let audio: String?

    var canWrite: Bool { !chars.isEmpty }
}

/// Writing only. ASL was cut; `asl` stays so a session someone else POSTs still decodes (and gets ignored).
enum Mode: String, Codable {
    case write, asl
}

struct SessionRequest: Encodable {
    let lang: String
    let phraseId: String
    let charIndex: Int
    let mode: Mode
}

struct SessionState: Decodable, Equatable {
    let lang: String
    let langName: String?
    let rtl: Bool?
    let phraseId: String
    let text: String?
    let char: String?
    let charIndex: Int
    let totalChars: Int
    let romanization: String?
    let meaning: String?
    let audioUrl: String?
    let strokeUrl: String?
    let mode: Mode
    let version: Int?

    var isRTL: Bool { rtl ?? false }
}

struct GradeResult: Decodable, Equatable, Identifiable {
    let correct: Bool
    let score: Double
    let feedback: String
    let ts: Double
    let seen: String?
    let char: String?
    let lang: String?

    var id: Double { ts }
    var scoreInt: Int { Int(score.rounded()) }
}

struct Health: Decodable {
    let ok: Bool
    let modelReady: Bool?
    let fakeGrade: Bool?
}
