import Foundation

enum VoiceCommand: Equatable, Sendable {
    case next, again, slower, check
    case switchTo(lang: String)
    case helpMeWrite(message: String, lang: String?)
}

/// Turns a running transcript into commands. Pure, so it's unit-tested.
enum VoiceCommandParser {
    /// Spoken names → lesson ids.
    static let languageNames: [String: String] = [
        "mandarin": "mandarin", "chinese": "mandarin", "mandarin chinese": "mandarin",
        "hindi": "hindi", "devanagari": "hindi",
        "arabic": "arabic",
        "russian": "russian", "cyrillic": "russian",
        "hebrew": "hebrew",
        "greek": "greek",
    ]

    static func language(in text: String) -> String? {
        let t = text.lowercased()
        // Longest names first so "mandarin chinese" wins over "chinese".
        for name in languageNames.keys.sorted(by: { $0.count > $1.count }) where t.range(of: "\\b\(name)\\b", options: .regularExpression) != nil {
            return languageNames[name]
        }
        return nil
    }

    /// Parse the newest words of a transcript (the recognizer gives the whole utterance so far).
    static func parse(_ utterance: String) -> VoiceCommand? {
        let t = utterance.lowercased()
            .replacingOccurrences(of: "[^a-z' ]", with: " ", options: .regularExpression)
            .split(separator: " ").joined(separator: " ")
        guard !t.isEmpty else { return nil }

        if let r = t.range(of: #"(help me|how do i|how to) write (.+)"#, options: .regularExpression) {
            var rest = String(t[r]).replacingOccurrences(of: #"^(help me|how do i|how to) write "#, with: "", options: .regularExpression)
            var lang: String?
            if let inR = rest.range(of: #" in ([a-z ]+)$"#, options: .regularExpression), let l = language(in: String(rest[inR])) {
                lang = l
                rest = String(rest[..<inR.lowerBound])
            }
            rest = rest.trimmingCharacters(in: .whitespaces)
            // Wait for the message; "help me write" alone is not a command yet.
            guard !rest.isEmpty, rest.split(separator: " ").count <= 12 else { return nil }
            return .helpMeWrite(message: rest, lang: lang)
        }
        if t.range(of: #"\b(switch|change|go) to\b"#, options: .regularExpression) != nil, let l = language(in: t) {
            return .switchTo(lang: l)
        }
        let last = t.split(separator: " ").suffix(3).joined(separator: " ")
        if last.range(of: #"\b(next|next one|go on|continue|done)$"#, options: .regularExpression) != nil { return .next }
        if last.range(of: #"\b(again|repeat|one more time|start over)$"#, options: .regularExpression) != nil { return .again }
        if last.range(of: #"\b(slower|slow down|too fast)$"#, options: .regularExpression) != nil { return .slower }
        if last.range(of: #"\b(check|check it|grade|grade it|how did i do|finished)$"#, options: .regularExpression) != nil { return .check }
        return nil
    }
}
