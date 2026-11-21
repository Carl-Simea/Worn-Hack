import SwiftUI

/// Rainbow confetti. Bump `trigger` to fire a burst from `origin` (unit point in the view).
struct ConfettiView: View {
    let trigger: Int
    var origin = UnitPoint(x: 0.5, y: 0.42)
    var count = 140

    @State private var particles: [Particle] = []
    @State private var startedAt: Date?

    private static let life: TimeInterval = 2.6

    struct Particle {
        var angle: Double, speed: Double, spin: Double, size: CGFloat, color: Color, shape: Int, drift: Double
    }

    var body: some View {
        TimelineView(.animation(paused: startedAt == nil)) { timeline in
            Canvas { ctx, size in
                guard let start = startedAt else { return }
                let t = timeline.date.timeIntervalSince(start)
                guard t < Self.life else { return }
                let o = CGPoint(x: origin.x * size.width, y: origin.y * size.height)
                let fade = t > Self.life - 0.6 ? (Self.life - t) / 0.6 : 1
                for p in particles {
                    // Ballistic burst with air drag and gravity, plus a little flutter.
                    let drag: Double = (1 - exp(-2.2 * t)) / 2.2
                    let dx: Double = cos(p.angle) * p.speed * drag
                    let flutter: Double = sin(t * 6 + p.drift) * 8
                    let dy: Double = sin(p.angle) * p.speed * drag
                    let fall: Double = 190 * t * t
                    let x: CGFloat = o.x + CGFloat(dx + flutter)
                    let y: CGFloat = o.y + CGFloat(dy + fall)
                    var c = ctx
                    c.opacity = fade
                    c.translateBy(x: x, y: y)
                    c.rotate(by: .radians(p.spin * t))
                    let r = CGRect(x: -p.size / 2, y: -p.size / 4, width: p.size, height: p.shape == 0 ? p.size / 2 : p.size)
                    let path = p.shape == 2 ? Path(ellipseIn: r) : Path(roundedRect: r, cornerRadius: 1.5)
                    c.fill(path, with: .color(p.color))
                }
            }
        }
        .allowsHitTesting(false)
        .onChange(of: trigger) { _, _ in fire() }
        .accessibilityHidden(true)
    }

    private func fire() {
        particles = (0..<count).map { _ in
            Particle(angle: Double.random(in: -Double.pi * 0.95 ... -Double.pi * 0.05),
                     speed: Double.random(in: 380...920),
                     spin: Double.random(in: -12...12),
                     size: CGFloat.random(in: 7...13),
                     color: Theme.rainbow.randomElement()!,
                     shape: Int.random(in: 0...2),
                     drift: Double.random(in: 0...6.28))
        }
        startedAt = Date()
        Task {
            try? await Task.sleep(for: .seconds(Self.life + 0.1))
            startedAt = nil
        }
    }
}
