import CoreGraphics
import Foundation

/// Tier-1 auto-pacing: has new ink appeared inside the writing box since the last frame?
///
/// Runs fully on-device on a tiny grayscale thumbnail (64×64), so it takes well under a millisecond.
/// Each frame: crop to the writing box → downscale → threshold against the page's own brightness →
/// compare with the previous ink mask (dilated by one pixel, so jitter and small shifts don't count).
struct InkDiff: Sendable {
    struct Result: Equatable, Sendable {
        /// Fraction of the box that is ink now (0...1).
        var inkCoverage: Double
        /// Fraction of the box that became ink since the last accepted frame.
        var newInk: Double
        /// True when `newInk` crossed the stroke threshold.
        var strokeAdded: Bool
        /// The frame looked unusable (too dark, too uniform, or a big shift such as the page moving).
        var unusable: Bool
    }

    static let side = 64

    /// New-ink fraction that counts as "a stroke was drawn". A short stroke on a 64×64 box covers ~0.4%.
    var strokeThreshold = 0.0035
    /// Above this the page probably moved or the hand is in frame; ignore the frame.
    var maxPlausibleNewInk = 0.18

    private var previous: [Bool]?

    mutating func reset() { previous = nil }

    /// - Parameters:
    ///   - image: a camera frame.
    ///   - box: the writing box in normalized image coordinates (0...1, origin top-left).
    mutating func process(_ image: CGImage, box: CGRect = CGRect(x: 0.2, y: 0.2, width: 0.6, height: 0.6)) -> Result {
        guard let gray = Self.thumbnail(image, box: box) else {
            return Result(inkCoverage: 0, newInk: 0, strokeAdded: false, unusable: true)
        }
        return process(gray: gray)
    }

    /// Core comparison on an already-downscaled `side × side` grayscale buffer (exposed for tests).
    mutating func process(gray: [UInt8]) -> Result {
        let n = gray.count
        guard n == Self.side * Self.side else { return Result(inkCoverage: 0, newInk: 0, strokeAdded: false, unusable: true) }

        // Paper brightness = 70th percentile (robust to ink and shadows). Ink = clearly darker than paper.
        var hist = [Int](repeating: 0, count: 256)
        for v in gray { hist[Int(v)] += 1 }
        var acc = 0, paper = 255
        for level in 0..<256 { acc += hist[level]; if acc >= n * 7 / 10 { paper = level; break } }
        guard paper > 60 else { return Result(inkCoverage: 0, newInk: 0, strokeAdded: false, unusable: true) }  // too dark
        let cutoff = Int(Double(paper) * 0.62)

        var mask = [Bool](repeating: false, count: n)
        var inkCount = 0
        for i in 0..<n where Int(gray[i]) < cutoff { mask[i] = true; inkCount += 1 }
        let coverage = Double(inkCount) / Double(n)

        guard let prev = previous else {
            previous = mask
            return Result(inkCoverage: coverage, newInk: 0, strokeAdded: false, unusable: false)
        }

        let grown = Self.dilate(prev)
        var fresh = 0
        for i in 0..<n where mask[i] && !grown[i] { fresh += 1 }
        let newInk = Double(fresh) / Double(n)

        if newInk > maxPlausibleNewInk {
            // Page moved or a hand covers the box: re-baseline, don't advance.
            previous = mask
            return Result(inkCoverage: coverage, newInk: newInk, strokeAdded: false, unusable: true)
        }
        let added = newInk >= strokeThreshold
        if added { previous = mask }   // accept the new ink as the baseline only once it counts
        return Result(inkCoverage: coverage, newInk: newInk, strokeAdded: added, unusable: false)
    }

    private static func dilate(_ m: [Bool]) -> [Bool] {
        let s = side
        var out = m
        for y in 0..<s {
            for x in 0..<s where m[y * s + x] {
                for dy in -1...1 {
                    for dx in -1...1 {
                        let nx = x + dx, ny = y + dy
                        if nx >= 0, ny >= 0, nx < s, ny < s { out[ny * s + nx] = true }
                    }
                }
            }
        }
        return out
    }

    /// Crop + downscale + grayscale via CoreGraphics (hardware-accelerated, on-device).
    static func thumbnail(_ image: CGImage, box: CGRect) -> [UInt8]? {
        let w = CGFloat(image.width), h = CGFloat(image.height)
        let crop = CGRect(x: box.minX * w, y: box.minY * h, width: box.width * w, height: box.height * h).integral
        guard let cropped = image.cropping(to: crop) else { return nil }
        var buf = [UInt8](repeating: 0, count: side * side)
        let ok: Bool = buf.withUnsafeMutableBytes { raw in
            guard let ctx = CGContext(data: raw.baseAddress, width: side, height: side, bitsPerComponent: 8,
                                      bytesPerRow: side, space: CGColorSpaceCreateDeviceGray(),
                                      bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return false }
            ctx.interpolationQuality = .medium
            ctx.draw(cropped, in: CGRect(x: 0, y: 0, width: side, height: side))
            return true
        }
        return ok ? buf : nil
    }
}
