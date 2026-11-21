import SwiftUI

/// Draws a character stroke by stroke: done strokes in ink, the current one animating, the rest faint.
/// `style: .glasses` mirrors the glasses display (black, bright strokes).
struct StrokeCanvas: View {
    enum Style { case paper, glasses }

    let lang: String
    let char: String
    let strokes: StrokeData?
    /// 1-based stroke being demonstrated. `0` = show the whole character at rest.
    let shown: Int
    /// Changes restart the current-stroke animation.
    let epoch: Int
    var speed: Double = 1
    var style: Style = .paper
    var showGrid = true
    /// Dictation: hide the character until it's revealed.
    var hidden = false
    /// Numbered badges at each stroke's start (stroke order at a glance).
    var numbers = false

    @State private var progress: CGFloat = 1

    private var inkColor: Color { style == .glasses ? Theme.glassesStroke : Theme.ink }
    private var faint: Color { style == .glasses ? Theme.glassesDim : Theme.ink.opacity(0.09) }
    private var current: Color { style == .glasses ? Theme.glassesStroke : Theme.accent }

    var body: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height)
            let rect = CGRect(x: (geo.size.width - side) / 2, y: (geo.size.height - side) / 2, width: side, height: side)
            ZStack {
                if showGrid { grid(rect) }
                if hidden {
                    Text("?")
                        .font(Theme.display(side * 0.42, weight: .light))
                        .foregroundStyle(faint.opacity(style == .glasses ? 4 : 3))
                        .position(x: rect.midX, y: rect.midY)
                } else if let strokes, strokes.count > 0 {
                    strokeLayers(strokes, rect: rect.insetBy(dx: side * 0.06, dy: side * 0.06))
                } else {
                    tracedGlyph(side: side, rect: rect)
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .onAppear { animate() }
        .onChange(of: epoch) { _, _ in animate() }
        .accessibilityElement()
        .accessibilityLabel(hidden ? "Hidden character" : "\(char), stroke \(max(shown, 1)) of \(strokes?.count ?? 1)")
    }

    private func animate() {
        progress = 0
        withAnimation(.easeInOut(duration: 0.85 * speed)) { progress = 1 }
    }

    // MARK: layers

    @ViewBuilder
    private func strokeLayers(_ data: StrokeData, rect: CGRect) -> some View {
        let lineWidth = rect.width * 0.075
        ForEach(Array(data.strokes.enumerated()), id: \.offset) { i, s in
            let n = i + 1
            let color: Color = shown == 0 || n < shown ? inkColor : (n == shown ? current : faint)
            let trim: CGFloat = n == shown ? progress : 1
            if let outline = s.outline {
                // hanzi-writer: fill the outline, revealed along its median (like a brush moving).
                OpsShape(ops: outline).fill(color)
                    .mask {
                        OpsShape(ops: s.centerline)
                            .trim(from: 0, to: trim)
                            .stroke(style: StrokeStyle(lineWidth: rect.width * 0.16, lineCap: .round, lineJoin: .round))
                    }
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
            } else {
                OpsShape(ops: s.centerline)
                    .trim(from: 0, to: trim)
                    .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
            }
            if numbers && shown > 0 && n <= shown, let start = s.centerline.first.flatMap(Self.point) {
                let d = max(22, rect.width * 0.1)
                Text("\(n)")
                    .font(.system(size: d * 0.6, weight: .bold, design: .rounded)).foregroundStyle(.white)
                    .frame(width: d, height: d)
                    .background(n == shown ? Theme.accent : Theme.ink.opacity(0.6), in: Circle())
                    .position(x: rect.minX + start.x * rect.width, y: rect.minY + start.y * rect.height)
                    .opacity(n == shown && progress < 0.05 ? 0 : 1)
            } else if n == shown && shown > 0, let start = s.centerline.first.flatMap(Self.point) {
                // Where the pen starts.
                Circle().fill(current).frame(width: lineWidth * 1.1, height: lineWidth * 1.1)
                    .position(x: rect.minX + start.x * rect.width, y: rect.minY + start.y * rect.height)
                    .opacity(progress < 0.98 ? 1 : 0.35)
            }
        }
    }

    /// No stroke data for this script: trace the font glyph.
    private func tracedGlyph(side: CGFloat, rect: CGRect) -> some View {
        ZStack {
            Text(char)
                .font(Theme.script(lang, size: side * (char.count > 2 ? 0.30 : 0.62)))
                .foregroundStyle(faint.opacity(style == .glasses ? 2.5 : 1.6))
            Text(char)
                .font(Theme.script(lang, size: side * (char.count > 2 ? 0.30 : 0.62)))
                .foregroundStyle(current)
                .mask(alignment: ScriptInfo.isRTL(lang) ? .trailing : .leading) {
                    Rectangle().frame(width: side * progress)
                }
        }
        .minimumScaleFactor(0.3)
        .lineLimit(1)
        .environment(\.layoutDirection, ScriptInfo.isRTL(lang) ? .rightToLeft : .leftToRight)
        .frame(width: rect.width, height: rect.height)
        .position(x: rect.midX, y: rect.midY)
    }

    private func grid(_ rect: CGRect) -> some View {
        let c = style == .glasses ? Color.white.opacity(0.10) : Theme.ink.opacity(0.08)
        return ZStack {
            Rectangle().strokeBorder(c, lineWidth: 1)
            Path { p in
                p.move(to: CGPoint(x: rect.width / 2, y: 0)); p.addLine(to: CGPoint(x: rect.width / 2, y: rect.height))
                p.move(to: CGPoint(x: 0, y: rect.height / 2)); p.addLine(to: CGPoint(x: rect.width, y: rect.height / 2))
                p.move(to: .zero); p.addLine(to: CGPoint(x: rect.width, y: rect.height))
                p.move(to: CGPoint(x: rect.width, y: 0)); p.addLine(to: CGPoint(x: 0, y: rect.height))
            }
            .stroke(c, style: StrokeStyle(lineWidth: 1, dash: [4, 6]))
        }
        .frame(width: rect.width, height: rect.height)
        .position(x: rect.midX, y: rect.midY)
    }

    private static func point(_ op: PathOp) -> CGPoint? {
        switch op {
        case .move(let p), .line(let p), .quad(let p, _), .cubic(let p, _, _): return p
        case .close: return nil
        }
    }
}

/// SwiftUI shape from parsed path ops (unit square → frame).
struct OpsShape: Shape {
    let ops: [PathOp]
    func path(in rect: CGRect) -> Path { Path(ops.cgPath(in: rect)) }
}
