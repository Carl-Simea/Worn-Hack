import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// Worn's look: warm paper, deep ink, one vivid accent (seal vermilion). Dark mode = ink black + chalk white.
enum Theme {
    static let paper = Color(light: 0xF4EFE6, dark: 0x0E0F12)
    static let card = Color(light: 0xFBF8F2, dark: 0x17191E)
    static let ink = Color(light: 0x1B1D24, dark: 0xECE8DF)
    static let inkSoft = Color(light: 0x5C5E66, dark: 0xA19D95)
    static let hairline = Color(light: 0xE2DACB, dark: 0x2A2D34)
    /// The one loud color: a calligrapher's seal.
    static let accent = Color(light: 0xE0402A, dark: 0xFF5A43)
    static let good = Color(light: 0x2F7D4F, dark: 0x5BD68A)
    static let warn = Color(light: 0xB86A12, dark: 0xF2B04A)

    /// Glasses display: pure black (transparent on the optics) with bright strokes.
    static let glassesBG = Color.black
    static let glassesStroke = Color(red: 0.55, green: 1.0, blue: 0.86)
    static let glassesDim = Color.white.opacity(0.14)

    static let corner: CGFloat = 22

    // Typography: New York (system serif) for display, SF for everything else.
    static func display(_ size: CGFloat, weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight, design: .serif) }
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight) }

    /// Script glyphs: bundled Noto (Resources/Fonts) when present, otherwise the system's font for that script.
    static func script(_ lang: String?, size: CGFloat) -> Font {
        if let name = notoName(lang), FontRegistry.has(name) { return .custom(name, size: size) }
        return .system(size: size, weight: .regular)
    }

    static func notoName(_ lang: String?) -> String? {
        switch lang {
        case "mandarin": return "NotoSansSC-Regular"
        case "hindi": return "NotoSansDevanagari-Regular"
        case "arabic": return "NotoNaskhArabic-Regular"
        case "russian", "greek": return "NotoSans-Regular"
        case "hebrew": return "NotoSansHebrew-Regular"
        default: return nil
        }
    }

    static let rainbow: [Color] = [
        Color(red: 1, green: 0.27, blue: 0.27), Color(red: 1, green: 0.6, blue: 0.1), Color(red: 1, green: 0.85, blue: 0.2),
        Color(red: 0.3, green: 0.85, blue: 0.4), Color(red: 0.2, green: 0.6, blue: 1), Color(red: 0.55, green: 0.35, blue: 1),
        Color(red: 1, green: 0.4, blue: 0.75),
    ]
}

/// Home-screen heroes and one-line script notes. Lesson JSON (`script`, `about`) wins when present.
enum ScriptInfo {
    static let order = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]

    static func hero(_ lang: String) -> String {
        ["mandarin": "你好", "hindi": "नमस्ते", "arabic": "مرحبا", "russian": "Привет", "hebrew": "שלום", "greek": "Γεια σου"][lang] ?? ""
    }

    static func script(_ lang: String) -> String {
        ["mandarin": "Simplified hanzi", "hindi": "Devanagari", "arabic": "Arabic script",
         "russian": "Cyrillic", "hebrew": "Hebrew script", "greek": "Greek alphabet"][lang] ?? ""
    }

    static func blurb(_ lang: String) -> String {
        [
            "mandarin": "One character, one syllable, one meaning.",
            "hindi": "Letters hang from a top line, drawn last.",
            "arabic": "Right to left. Dots come after the stroke.",
            "russian": "Some letters look Latin but aren't.",
            "hebrew": "Right to left. Vowels mostly unwritten.",
            "greek": "Familiar shapes, different sounds.",
        ][lang] ?? ""
    }

    static func isRTL(_ lang: String) -> Bool { lang == "arabic" || lang == "hebrew" }
}

enum FontRegistry {
    private static var cache: [String: Bool] = [:]
    static func has(_ name: String) -> Bool {
        if let v = cache[name] { return v }
        #if canImport(UIKit)
        let v = UIFont(name: name, size: 12) != nil
        #else
        let v = false
        #endif
        cache[name] = v
        return v
    }
}

extension Color {
    init(light: UInt32, dark: UInt32) {
        #if canImport(UIKit)
        self = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
        #else
        self = Color(hex: light)
        #endif
    }

    init(hex: UInt32) {
        self = Color(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }
}

#if canImport(UIKit)
extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}
#endif

// MARK: reusable bits

struct CardBackground: ViewModifier {
    var padding: CGFloat = 18
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous).strokeBorder(Theme.hairline, lineWidth: 1))
    }
}

extension View {
    func card(padding: CGFloat = 18) -> some View { modifier(CardBackground(padding: padding)) }
}

/// Springy press feedback for big tappable cards.
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(17, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(Theme.accent, in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

struct QuietButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(15, weight: .medium))
            .foregroundStyle(Theme.ink)
            .padding(.horizontal, 16).frame(minHeight: 46)
            .background(Theme.card, in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.spring(response: 0.3, dampingFraction: 0.6), value: configuration.isPressed)
    }
}

/// Progress ring per language.
struct Ring: View {
    var value: Double
    var lineWidth: CGFloat = 5
    var color: Color = Theme.accent

    var body: some View {
        ZStack {
            Circle().stroke(Theme.hairline, lineWidth: lineWidth)
            Circle()
                .trim(from: 0, to: min(1, value))
                .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .opacity(value > 0.005 ? 1 : 0)
                .rotationEffect(.degrees(-90))
                .animation(.spring(response: 0.8, dampingFraction: 0.8), value: value)
        }
    }
}

/// Small uppercase label.
struct Eyebrow: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(Theme.sans(11, weight: .semibold))
            .tracking(1.4)
            .foregroundStyle(Theme.inkSoft)
    }
}
