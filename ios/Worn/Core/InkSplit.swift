import CoreGraphics
import Foundation

/// Finds the horizontal ink clusters on a photo of a written line (letters of one word side by side), so a single
/// letter can be graded without the letters already written next to it.
enum InkSplit {
    /// Normalised x-ranges (0…1) of ink clusters, left to right. Clusters closer than `gap` × ink height are merged.
    static func clusters(in img: CGImage, gap: CGFloat = 0.45) -> [ClosedRange<CGFloat>] {
        let w = 240
        let h = max(8, Int(CGFloat(w) * CGFloat(img.height) / CGFloat(max(1, img.width))))
        var px = [UInt8](repeating: 0, count: w * h)
        guard let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w,
                                  space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return [] }
        ctx.interpolationQuality = .medium
        ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
        let sorted = px.sorted()
        let paper = Double(sorted[sorted.count * 6 / 10])
        let cut = UInt8(max(20, paper * 0.5))        // pencil/pen is much darker than paper or blue ruled lines
        var col = [Int](repeating: 0, count: w)
        var minY = h, maxY = 0
        for y in 0..<h { for x in 0..<w where px[y * w + x] < cut { col[x] += 1; minY = min(minY, y); maxY = max(maxY, y) } }
        guard maxY > minY else { return [] }
        // A column counts as ink only with a few dark pixels (thin vertical ruled lines are one pixel wide and light).
        let inkH = CGFloat(maxY - minY + 1)
        let minPix = max(2, Int(inkH * 0.06))
        var runs: [(Int, Int)] = []
        var start: Int?
        for x in 0..<w {
            if col[x] >= minPix { if start == nil { start = x } }
            else if let s = start { runs.append((s, x - 1)); start = nil }
        }
        if let s = start { runs.append((s, w - 1)) }
        let maxGap = Int(inkH * gap)
        var merged: [(Int, Int)] = []
        for r in runs {
            if let l = merged.last, r.0 - l.1 <= maxGap { merged[merged.count - 1].1 = r.1 } else { merged.append(r) }
        }
        return merged.filter { $0.1 - $0.0 >= 2 }.map { CGFloat($0.0) / CGFloat(w)...CGFloat($0.1 + 1) / CGFloat(w) }
    }

    /// The x-range of the letter written last: rightmost cluster for left-to-right scripts, leftmost for right-to-left.
    static func newest(in img: CGImage, rtl: Bool) -> ClosedRange<CGFloat>? {
        let c = clusters(in: img)
        return rtl ? c.first : c.last
    }
}
