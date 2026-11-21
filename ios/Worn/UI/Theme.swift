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
    static func sans(_ size: CGFloat, weight: Font.Weight = .regular) -> Font { .system(size: max(size, 14), weight: weight) }  // nothing smaller than 14 pt

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
        EmptyView()  // minimal: section labels removed; the cards speak for themselves
    }
}


/// The Scribi mark (glasses-frame stroke), drawn as a vector so it is sharp at any size. Box 780 x 282.
struct ScribiMark: Shape {
    static let d = "M10.8,127C11,131.1 11.5,136.1 12.2,140.5C13,144.9 13.3,147.4 15.2,153.5C17.2,159.6 22.3,173 24,177C25.7,181 24.6,180.3 25.2,177.5C25.9,174.7 26.8,165.5 27.8,160.2C28.7,155 29.8,150.5 31,146C32.2,141.5 33.5,137.5 35.2,133C37,128.5 39.5,122.9 41.8,118.8C44,114.6 46.2,111.2 48.5,108C50.8,104.8 51.8,103.1 55.8,99.2C59.7,95.4 67.5,88.3 72,84.8C76.5,81.2 79.4,79.7 82.8,77.8C86.1,75.8 86.4,75.4 92,73.2C97.6,71.1 107.2,67.2 116.5,64.8C125.8,62.3 135.7,60.2 148,58.5C160.3,56.8 176.3,55.4 190.2,54.5C204.2,53.6 217.4,53.2 231.5,53C245.6,52.8 261.6,52.7 274.8,53C287.9,53.3 300.5,53.8 310.2,54.8C320,55.7 327.2,56.9 333.5,58.5C339.8,60.1 343.9,62.2 347.8,64.2C351.6,66.3 354.2,68.5 356.8,70.8C359.3,73 361.1,74.8 363.2,78C365.4,81.2 367.8,87 369.8,90C371.8,93 373.2,94.5 375.2,96.2C377.3,98 379.2,99.2 382,100.2C384.8,101.3 388.2,102.2 391.8,102.5C395.3,102.8 399.7,102.5 403.2,101.8C406.8,101 410.4,99.4 413,97.8C415.6,96.1 416.8,94.9 419,91.8C421.2,88.6 424.4,81.8 426.2,78.8C428.1,75.8 428.2,75.8 430.2,73.8C432.3,71.7 435.8,68.5 438.5,66.5C441.2,64.5 443.9,63.3 446.8,62C449.6,60.7 452.5,59.7 455.8,58.8C459,57.8 458.6,57.3 466,56.5C473.4,55.7 485.5,54.2 500,53.8C514.5,53.2 539.2,53.4 552.8,53.5C566.2,53.6 571.2,54 581,54.5C590.8,55 602.5,55.9 611.5,56.8C620.5,57.6 627.8,58.6 635.2,59.8C642.7,60.9 648,61.8 656,63.8C664,65.8 675.7,69 683,71.8C690.3,74.5 695.6,77.5 700,80.2C704.4,83 706.8,85.2 709.2,88C711.7,90.8 713.3,94 714.5,97C715.7,100 716.2,103 716.2,106.2C716.3,109.5 715.6,113 714.8,116.2C713.9,119.5 712.9,122.2 711.2,125.8C709.6,129.3 707.6,133.2 704.8,137.5C701.9,141.8 699.8,145.5 694,151.8C688.2,158 677,168.8 670.2,174.8C663.5,180.7 659.3,183.5 653.8,187.5C648.2,191.5 644.8,194 636.8,199C628.7,204 618,210.6 605.5,217.2C593,223.9 581.4,230 562,238.8C542.6,247.5 501.2,264.3 489.2,269.5C477.3,274.7 481.2,271.9 490.5,269.8C499.8,267.6 529.4,260.7 545,256.5C560.6,252.3 573.4,248 584.2,244.5C595.1,241 598.1,240.1 610,235.5C621.9,230.9 643.1,222.3 655.5,216.8C667.9,211.2 676.8,206.2 684.2,202.2C691.7,198.3 695,196.1 700,193C705,189.9 708.7,187.6 714,183.8C719.3,179.9 726.6,174.5 731.8,170C736.9,165.5 741.3,161 745,157C748.7,153 750.9,150.4 753.8,146.2C756.6,142.1 760,136.8 762.2,132.2C764.5,127.7 766.1,123 767.2,119C768.4,115 768.9,111.8 769.2,108C769.6,104.2 769.7,100.5 769.2,96.2C768.8,92 768.1,87.1 766.5,82.2C764.9,77.4 762.3,71.6 759.5,67C756.7,62.4 753.5,58.4 749.8,54.5C746,50.6 741.8,47 737.2,43.8C732.7,40.5 727.4,37.4 722.2,34.8C717.1,32.1 713.1,30.1 706.2,27.8C699.4,25.4 689.5,22.5 681.2,20.5C673,18.5 668.4,17.5 656.5,16C644.6,14.5 624,12.6 609.8,11.8C595.5,10.9 625.9,11 571.2,10.8C516.6,10.5 346.5,10.1 281.8,10.2C217,10.4 204.8,10.9 182.5,11.5C160.2,12.1 157.2,13.1 148,14C138.8,14.9 134.1,15.6 127.2,16.8C120.4,17.9 113.1,19.2 106.8,20.8C100.4,22.2 94,24.1 89,25.8C84,27.4 80.8,28.6 76.5,30.5C72.2,32.4 67,35 63.2,37C59.5,39 57.2,40.5 54,42.8C50.8,45 46.8,48 43.8,50.8C40.7,53.5 38,56.2 35.5,59C33,61.8 30.8,64.3 28.5,67.5C26.2,70.7 23.9,74.2 21.8,78.2C19.6,82.3 17.3,87.4 15.8,91.8C14.2,96.1 13.1,100.2 12.2,104.2C11.4,108.2 11,112 10.8,115.8C10.5,119.5 10.5,122.9 10.8,127Z"
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let sx = rect.width / 780, sy = rect.height / 282
        let scanner = ScribiMark.d.replacingOccurrences(of: "M", with: " M ").replacingOccurrences(of: "C", with: " C ")
            .replacingOccurrences(of: "Z", with: " Z ").replacingOccurrences(of: ",", with: " ")
            .split(separator: " ").map(String.init)
        var i = 0, cmd = ""
        func num() -> CGFloat { defer { i += 1 }; return CGFloat(Double(scanner[i]) ?? 0) }
        func pt() -> CGPoint { let x = num(), y = num(); return CGPoint(x: rect.minX + x * sx, y: rect.minY + y * sy) }
        while i < scanner.count {
            let t = scanner[i]
            if t == "M" || t == "C" || t == "Z" { cmd = t; i += 1; if t == "Z" { p.closeSubpath() }; continue }
            if cmd == "M" { p.move(to: pt()); cmd = "C" }
            else if cmd == "C" { let c1 = pt(), c2 = pt(), e = pt(); p.addCurve(to: e, control1: c1, control2: c2) }
            else { i += 1 }
        }
        return p
    }
}
