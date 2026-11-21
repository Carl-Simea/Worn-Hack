import Foundation

/// Offline "Write your name": English name → approximate spelling in five scripts, using the team's sound tables
/// (content/names/*.json). Used only when the server's /name can't answer. Approximate by design.
///
/// Stage 1 turns English spelling into simple sounds (digraphs, soft c, silent e, y as a vowel…).
/// Stage 2 renders those sounds with each script's rules (Devanagari syllables and vowel signs, Arabic long vowels,
/// Hebrew consonant spelling with final forms, Greek with final ς, Cyrillic with я/ю).
enum NameSpeller {
    enum Sound: Equatable { case c(String), v(String) }

    static let vowels: Set<Character> = ["a", "e", "i", "o", "u"]

    // MARK: stage 1

    static func sounds(_ name: String, keepDoubles: Bool = false, voicedS: Bool = false) -> [Sound] {
        var s = Array(name.lowercased().filter { $0.isLetter && $0.isASCII })
        guard !s.isEmpty else { return [] }
        // Silent final e after a single consonant ("Mike", "Kate", "Jane"): lengthen the vowel before it.
        var magic: Character?
        var softFinalC = false
        if s.count >= 4, s.last == "e", !vowels.contains(s[s.count - 2]), vowels.contains(s[s.count - 3]),
           !vowels.contains(s[s.count - 4]) {
            magic = s[s.count - 3]
            softFinalC = s[s.count - 2] == "c"      // "Grace"
            s.removeLast()
        }
        var out: [Sound] = []
        var i = 0
        func at(_ k: Int) -> Character? { k >= 0 && k < s.count ? s[k] : nil }
        while i < s.count {
            let ch = s[i], nx = at(i + 1)
            let pair = String([ch] + (nx.map { [$0] } ?? []))
            // Vowels
            if vowels.contains(ch) || (ch == "y" && i > 0 && !(nx.map(vowels.contains) ?? false)) {
                if ch == "y" {
                    // "Nyla", "Kyle": y between consonants sounds like "eye"; at the end it's "ee".
                    let between = i > 0 && !vowels.contains(s[i - 1]) && nx != nil
                    out.append(.v(between ? "ai" : "i")); i += 1; continue
                }
                if ["ee", "ea", "ie"].contains(pair) && !(pair == "ie" && i + 2 == s.count) { out.append(.v("ee")); i += 2; continue }
                if pair == "oo" || pair == "ou" { out.append(.v("oo")); i += 2; continue }
                if pair == "ai" || pair == "ay" || pair == "ey" { out.append(.v("ei")); i += 2; continue }
                if pair == "au" || pair == "aw" { out.append(.v("au")); i += 2; continue }
                if i == s.count - 2, let m = magic, m == ch, i + 1 < s.count {
                    switch ch {
                    case "a": out.append(.v("ei"))
                    case "i": out.append(.v("ai"))
                    case "e": out.append(.v("ee"))
                    case "u": out.append(.v("oo"))
                    default: out.append(.v(String(ch)))
                    }
                    i += 1; continue
                }
                out.append(.v(String(ch))); i += 1; continue
            }
            // Consonants
            if ["sh", "ch", "th", "kh", "ph", "ck", "gh", "wh", "zh"].contains(pair) {
                switch pair {
                case "ph": out.append(.c("f"))
                case "ck": out.append(.c("k"))
                case "wh": out.append(.c("w"))
                case "gh": if i == 0 { out.append(.c("g")) }          // silent elsewhere ("Leigh")
                default: out.append(.c(pair))
                }
                i += 2; continue
            }
            switch ch {
            case "c": out.append(.c(nx.map { "eiy".contains($0) } == true || (nx == nil && softFinalC) ? "s" : "k"))
            case "s":
                // Between vowels an English s usually sounds like z ("Lisa", "Rose").
                let intervocalic = i > 0 && vowels.contains(s[i - 1]) && (nx.map(vowels.contains) ?? false)
                out.append(.c(voicedS && intervocalic ? "z" : "s"))
            case "q": out.append(.c("k")); if nx == "u" { out.append(.c("w")); i += 1 }
            case "x": out.append(.c("k")); out.append(.c("s"))
            case "h":
                // h after a vowel at the end ("Sarah", "Hannah") is silent; mark it for "-ah" endings.
                // After a vowel and before a consonant it's silent too ("John").
                if i == s.count - 1, i > 0, vowels.contains(s[i - 1]) { out.append(.c("h-end")) }
                else if i > 0, vowels.contains(s[i - 1]), let n = nx, !vowels.contains(n) { }
                else { out.append(.c("h")) }
            default: out.append(.c(String(ch)))
            }
            // Doubled consonants ("Emma", "Anna") collapse except where a script writes them twice.
            if !keepDoubles, let n = nx, n == ch, !vowels.contains(ch) { i += 1 }
            i += 1
        }
        return out
    }

    // MARK: stage 2

    static func spell(_ name: String, table: NameTable) -> String {
        switch table.lang {
        case "hindi": return devanagari(sounds(name, keepDoubles: true), table.sounds)
        case "arabic": return arabic(sounds(name, voicedS: true), table.sounds)
        case "hebrew": return hebrew(sounds(name), table.sounds)
        case "greek": return greek(sounds(name, keepDoubles: true, voicedS: true), table.sounds)
        case "russian": return cyrillic(sounds(name, keepDoubles: true, voicedS: true), table.sounds)
        default: return ""
        }
    }

    private static func cons(_ c: String) -> String { c == "h-end" ? "h" : c }

    static func cyrillic(_ ss: [Sound], _ t: [String: String]) -> String {
        var out = ""
        for (k, s) in ss.enumerated() {
            let prevVowel = k > 0 && { if case .v = ss[k - 1] { return true }; return false }()
            switch s {
            case .c("h-end"): continue
            case .c(let c): out += t[c] ?? t[String(c.prefix(1))] ?? ""
            case .v(let v):
                if prevVowel || (k > 0 && ss[k - 1] == .c("y")) {
                    if out.hasSuffix("й") { out.removeLast() }
                    switch v {
                    case "a": out += "я"; continue
                    case "u", "oo": out += "ю"; continue
                    case "e": out += "е"; continue
                    default: break
                    }
                }
                switch v {
                case "a": out += "а"
                case "e": out += k == 0 ? "э" : "е"
                case "i", "ee": out += "и"
                case "o": out += "о"
                case "u", "oo": out += "у"
                case "ai": out += "ай"
                case "ei": out += "ей"
                case "au": out += "ау"
                default: break
                }
            }
        }
        return capitalized(out)
    }

    static func greek(_ ss: [Sound], _ t: [String: String]) -> String {
        var out = ""
        for s in ss {
            switch s {
            case .c("h-end"): continue
            case .c("y"): out += "γι"
            case .c(let c): out += t[c] ?? t[String(c.prefix(1))] ?? ""
            case .v(let v):
                switch v {
                case "a": out += "α"
                case "e": out += "ε"
                case "i", "ee": out += "ι"
                case "o": out += "ο"
                case "u", "oo": out += "ου"
                case "ai": out += "αι"
                case "ei": out += "ει"
                case "au": out += "αου"
                default: break
                }
            }
        }
        if out.hasSuffix("σ") { out = String(out.dropLast()) + "ς" }
        return capitalized(out)
    }

    static func hebrew(_ ss: [Sound], _ t: [String: String]) -> String {
        let vowelCount = ss.filter { if case .v = $0 { return true }; return false }.count
        var out = ""
        for (k, s) in ss.enumerated() {
            let isFirst = k == 0, isLast = k == ss.count - 1
            switch s {
            case .c("h-end"): if !out.hasSuffix("ה") { out += "ה" }
            case .c(let c):
                // Final forms for m, n, f, ts; English k stays ק ("Mike" → מייק).
                let key = isLast && c != "k" && t[c + "$"] != nil ? c + "$" : c
                out += t[key] ?? t[String(c.prefix(1))] ?? ""
            case .v(let v):
                if isFirst {
                    out += "א"
                    if ["i", "ee", "ei"].contains(v) { out += "י" } else if ["o", "u", "oo"].contains(v) { out += "ו" }
                    continue
                }
                switch v {
                case "a", "e":
                    if isLast { out += "ה" } else if vowelCount == 1 && v == "a" { out += "א" }   // "Sam" → סאם
                case "i", "ee", "ei": out += "י"
                case "ai": out += "יי"
                case "o", "u", "oo", "au": out += "ו"
                default: break
                }
            }
        }
        return out
    }

    static func arabic(_ ss: [Sound], _ t: [String: String]) -> String {
        var out = ""
        for (k, s) in ss.enumerated() {
            let isLast = k == ss.count - 1
            switch s {
            case .c("h-end"): if out.hasSuffix("ا") { out.removeLast(); out += "ة" }
            case .c(let c): out += t[c] ?? t[String(c.prefix(1))] ?? ""
            case .v(let v):
                if k == 0 {
                    switch v {
                    case "a", "au": out += "أ"
                    case "o", "u", "oo": out += "أو"
                    default: out += "إ"
                    }
                    continue
                }
                switch v {
                case "a": out += "ا"
                case "e": out += isLast ? "ي" : "ي"
                case "i", "ee", "ei": out += "ي"
                case "o", "u", "oo", "au": out += "و"
                case "ai": out += "اي"
                default: break
                }
            }
        }
        return out
    }

    static func devanagari(_ ss: [Sound], _ t: [String: String]) -> String {
        // Vowel → (independent key, sign suffix for "consonant + vowel" keys)
        func vk(_ v: String) -> (String, String) {
            switch v {
            case "a": return ("A", "aa")
            case "e": return ("E", "e")
            case "i": return ("I", "i")
            case "ee": return ("EE", "ee")
            case "o": return ("O", "o")
            case "u": return ("U", "u")
            case "oo": return ("OO", "oo")
            case "ei": return ("E", "e")
            case "au": return ("AU", "au")
            case "ai": return ("AA", "aa")   // "Mike": माइक (aa + I) handled below
            default: return ("A", "aa")
            }
        }
        func base(_ c: String) -> String {
            switch c {
            case "w": return "v"
            case "c", "q": return "k"
            case "x": return "k"
            case "h-end": return ""
            default: return c
            }
        }
        var out = ""
        var k = 0
        while k < ss.count {
            switch ss[k] {
            case .v(let v):
                let prevIsVowel = k > 0 && { if case .v = ss[k - 1] { return true }; return false }()
                if prevIsVowel && (v == "a" || v == "u" || v == "o") {
                    // hiatus ("Maria"): y + vowel
                    out += t["y" + vk(v).1] ?? t[vk(v).0] ?? ""
                } else {
                    out += t[vk(v).0] ?? ""
                }
                if v == "ai" { out += t["I"] ?? "" }
                k += 1
            case .c(let c0):
                let c = base(c0)
                if c.isEmpty { k += 1; continue }
                if k + 1 < ss.count, case .v(let v) = ss[k + 1] {
                    let (_, sign) = vk(v)
                    out += t[c + sign] ?? ((t[c] ?? "") + (t[vk(v).0] ?? ""))
                    if v == "ai" { out += t["I"] ?? "" }
                    k += 2
                } else if k + 1 < ss.count {
                    out += t[c + "+"] ?? t[c] ?? ""      // half letter joins the next consonant
                    k += 1
                } else {
                    out += t[c] ?? ""                    // final consonant
                    k += 1
                }
            }
        }
        return out
    }

    private static func capitalized(_ s: String) -> String {
        guard let f = s.first else { return s }
        return String(f).uppercased() + s.dropFirst()
    }
}
