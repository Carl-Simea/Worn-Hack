import CoreGraphics
import Foundation

/// One character's stroke-order data, normalized to a unit square (0...1, y down).
///
/// Sources (see content/README.md):
/// - Mandarin: hanzi-writer-data JSON `{strokes: [svg outline], medians: [[[x,y]]]}` in a 1024 box, y up (baseline 900).
/// - Japanese: KanjiVG SVG, one centerline `<path d>` per stroke in a 109 box, y down.
/// - Hindi / Arabic / Russian: no stroke data; the UI traces the font glyph instead.
struct StrokeData: Equatable, Sendable {
    struct Stroke: Equatable, Sendable {
        /// Filled outline (hanzi-writer) or nil (KanjiVG has centerlines only).
        var outline: [PathOp]?
        /// Centerline in drawing order; animated with trim(from:to:).
        var centerline: [PathOp]
    }
    var strokes: [Stroke]

    var count: Int { strokes.count }

    // MARK: hanzi-writer JSON

    static func hanziWriter(_ data: Data) throws -> StrokeData {
        struct Raw: Decodable { let strokes: [String]; let medians: [[[Double]]] }
        let raw = try JSONDecoder().decode(Raw.self, from: data)
        // hanzi-writer: 1024 box, y axis points up with the baseline at 900 → flip.
        let map: (CGPoint) -> CGPoint = { CGPoint(x: $0.x / 1024, y: (900 - $0.y) / 1024) }
        var out: [Stroke] = []
        for (i, d) in raw.strokes.enumerated() {
            let outline = SVGPath.parse(d).map { $0.mapped(map) }
            let median = i < raw.medians.count ? raw.medians[i] : []
            var line: [PathOp] = []
            for (j, p) in median.enumerated() where p.count >= 2 {
                let pt = map(CGPoint(x: p[0], y: p[1]))
                line.append(j == 0 ? .move(pt) : .line(pt))
            }
            out.append(Stroke(outline: outline, centerline: line))
        }
        return StrokeData(strokes: out)
    }

    // MARK: KanjiVG SVG

    static func kanjiVG(_ data: Data) -> StrokeData {
        let svg = String(decoding: data, as: UTF8.self)
        var box: CGFloat = 109
        if let r = svg.range(of: #"viewBox="0 0 ([0-9.]+) ([0-9.]+)""#, options: .regularExpression) {
            let parts = svg[r].split(whereSeparator: { $0 == " " || $0 == "\"" })
            if parts.count >= 4, let w = Double(parts[3]) { box = CGFloat(w) }
        }
        var strokes: [Stroke] = []
        var search = svg.startIndex..<svg.endIndex
        while let r = svg.range(of: #"<path[^>]* d="([^"]+)""#, options: .regularExpression, range: search) {
            let tag = svg[r]
            if let d0 = tag.range(of: #" d=""#) {
                let d = tag[d0.upperBound...].dropLast()
                let ops = SVGPath.parse(String(d)).map { $0.mapped { CGPoint(x: $0.x / box, y: $0.y / box) } }
                if !ops.isEmpty { strokes.append(Stroke(outline: nil, centerline: ops)) }
            }
            search = r.upperBound..<svg.endIndex
        }
        return StrokeData(strokes: strokes)
    }
}

enum PathOp: Equatable, Sendable {
    case move(CGPoint)
    case line(CGPoint)
    case quad(CGPoint, control: CGPoint)
    case cubic(CGPoint, c1: CGPoint, c2: CGPoint)
    case close

    func mapped(_ f: (CGPoint) -> CGPoint) -> PathOp {
        switch self {
        case .move(let p): return .move(f(p))
        case .line(let p): return .line(f(p))
        case .quad(let p, let c): return .quad(f(p), control: f(c))
        case .cubic(let p, let a, let b): return .cubic(f(p), c1: f(a), c2: f(b))
        case .close: return .close
        }
    }
}

extension Array where Element == PathOp {
    /// Build a CGPath scaled into `rect`.
    func cgPath(in rect: CGRect) -> CGPath {
        let path = CGMutablePath()
        func s(_ p: CGPoint) -> CGPoint { CGPoint(x: rect.minX + p.x * rect.width, y: rect.minY + p.y * rect.height) }
        for op in self {
            switch op {
            case .move(let p): path.move(to: s(p))
            case .line(let p): path.addLine(to: s(p))
            case .quad(let p, let c): path.addQuadCurve(to: s(p), control: s(c))
            case .cubic(let p, let a, let b): path.addCurve(to: s(p), control1: s(a), control2: s(b))
            case .close: path.closeSubpath()
            }
        }
        return path
    }
}

/// SVG path-data parser covering M L H V Q T C S Z (absolute and relative). Arcs are not used by our sources.
enum SVGPath {
    static func parse(_ d: String) -> [PathOp] {
        var tokens = Tokenizer(d)
        var ops: [PathOp] = []
        var cur = CGPoint.zero, start = CGPoint.zero
        var lastCtrl: CGPoint?        // for S / T reflection
        var lastCmd: Character = " "
        var cmd: Character = " "

        while let next = tokens.peek() {
            if case .command(let c) = next { cmd = c; tokens.advance() } else if cmd == " " { break }
            let rel = cmd.isLowercase
            func pt() -> CGPoint? {
                guard let x = tokens.number(), let y = tokens.number() else { return nil }
                return rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
            }
            switch cmd.uppercased().first! {
            case "M":
                guard let p = pt() else { return ops }
                ops.append(.move(p)); cur = p; start = p; lastCtrl = nil
                cmd = rel ? "l" : "L"   // implicit lineto for following pairs
                lastCmd = "M"
                continue
            case "L":
                guard let p = pt() else { return ops }
                ops.append(.line(p)); cur = p; lastCtrl = nil
            case "H":
                guard let x = tokens.number() else { return ops }
                let p = CGPoint(x: rel ? cur.x + x : x, y: cur.y)
                ops.append(.line(p)); cur = p; lastCtrl = nil
            case "V":
                guard let y = tokens.number() else { return ops }
                let p = CGPoint(x: cur.x, y: rel ? cur.y + y : y)
                ops.append(.line(p)); cur = p; lastCtrl = nil
            case "Q":
                guard let c = pt(), let p = pt() else { return ops }
                ops.append(.quad(p, control: c)); lastCtrl = c; cur = p
            case "T":
                let c = ("QT".contains(lastCmd.uppercased()) ? lastCtrl.map { reflect($0, cur) } : nil) ?? cur
                guard let p = pt() else { return ops }
                ops.append(.quad(p, control: c)); lastCtrl = c; cur = p
            case "C":
                guard let a = pt(), let b = pt(), let p = pt() else { return ops }
                ops.append(.cubic(p, c1: a, c2: b)); lastCtrl = b; cur = p
            case "S":
                let a = ("CS".contains(lastCmd.uppercased()) ? lastCtrl.map { reflect($0, cur) } : nil) ?? cur
                guard let b = pt(), let p = pt() else { return ops }
                ops.append(.cubic(p, c1: a, c2: b)); lastCtrl = b; cur = p
            case "Z":
                ops.append(.close); cur = start; lastCtrl = nil
                lastCmd = "Z"
                cmd = " "
                continue
            default:
                return ops   // unsupported command (e.g. arcs): stop rather than draw garbage
            }
            lastCmd = cmd
        }
        return ops
    }

    private static func reflect(_ c: CGPoint, _ about: CGPoint) -> CGPoint {
        CGPoint(x: 2 * about.x - c.x, y: 2 * about.y - c.y)
    }

    private struct Tokenizer {
        enum Token { case command(Character), number(Double) }
        private let chars: [Character]
        private var i = 0
        init(_ s: String) { chars = Array(s) }

        private mutating func skip() {
            while i < chars.count, chars[i] == " " || chars[i] == "," || chars[i] == "\n" || chars[i] == "\t" || chars[i] == "\r" { i += 1 }
        }

        mutating func peek() -> Token? {
            skip()
            guard i < chars.count else { return nil }
            let c = chars[i]
            if c.isLetter && c != "e" && c != "E" { return .command(c) }
            let save = i
            defer { i = save }
            return number().map(Token.number)
        }

        mutating func advance() { skip(); i += 1 }

        mutating func number() -> Double? {
            skip()
            guard i < chars.count else { return nil }
            var s = ""
            var seenDot = false, seenExp = false
            if chars[i] == "-" || chars[i] == "+" { s.append(chars[i]); i += 1 }
            while i < chars.count {
                let c = chars[i]
                if c.isNumber { s.append(c) }
                else if c == "." && !seenDot && !seenExp { seenDot = true; s.append(c) }
                else if (c == "e" || c == "E") && !seenExp {
                    seenExp = true; s.append(c)
                    if i + 1 < chars.count, chars[i + 1] == "-" || chars[i + 1] == "+" { i += 1; s.append(chars[i]) }
                } else { break }
                i += 1
            }
            return Double(s)
        }
    }
}
