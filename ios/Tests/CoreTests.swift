import Foundation
import CoreGraphics
var fails = 0
func check(_ ok: Bool, _ m: String) { print(ok ? "PASS" : "FAIL", m); if !ok { fails += 1 } }
let root = URL(fileURLWithPath: CommandLine.arguments[1])

// Strokes: every real file parses with plausible counts and in-bounds points.
var total = 0, bad = 0
for lang in ((try? FileManager.default.contentsOfDirectory(atPath: root.path)) ?? []).sorted() where !lang.hasPrefix(".") {
  let dir = root.appendingPathComponent(lang)
  for f in ((try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []).sorted() where f.hasSuffix(".json") || f.hasSuffix(".svg") {
    let d = try! Data(contentsOf: dir.appendingPathComponent(f))
    let s = f.hasSuffix(".json") ? try! StrokeData.hanziWriter(d) : StrokeData.svgCenterlines(d)
    total += 1
    var pts: [CGPoint] = []
    for st in s.strokes { for op in st.centerline + (st.outline ?? []) { switch op { case .move(let p), .line(let p), .quad(let p, _), .cubic(let p, _, _): pts.append(p); case .close: break } } }
    let inBounds = pts.allSatisfy { $0.x > -0.15 && $0.x < 1.15 && $0.y > -0.15 && $0.y < 1.15 }
    if s.count == 0 || !inBounds || s.strokes.contains(where: { $0.centerline.count < 2 }) { bad += 1; print("  bad:", lang, f, s.count, inBounds) }
  }
}
check(bad == 0 && total > 0, "\(total) stroke files parse, all strokes in bounds")
let ni = try! StrokeData.hanziWriter(Data(contentsOf: root.appendingPathComponent("mandarin/4f60.json")))
check(ni.count == 7, "你 has 7 strokes (got \(ni.count))")
check(SVGPath.parse("M10 20 l5 5 h3 v-2 z").count == 5, "relative + h/v + z")
check(SVGPath.parse("M1,2c1-1,2,3,4.5.5").count == 2, "packed numbers (4.5.5)")

// Voice
check(VoiceCommandParser.parse("okay next") == .next, "voice: next")
check(VoiceCommandParser.parse("switch to Hebrew") == .switchTo(lang: "hebrew"), "voice: switch to Hebrew")
check(VoiceCommandParser.parse("help me write good morning in Greek") == .helpMeWrite(message: "good morning", lang: "greek"), "voice: help me write … in Greek")
check(VoiceCommandParser.parse("help me write") == nil, "voice: incomplete compose ignored")
check(VoiceCommandParser.parse("can you go slower") == .slower && VoiceCommandParser.parse("check it") == .check && VoiceCommandParser.parse("again") == .again, "voice: slower/check/again")
check(VoiceCommandParser.parse("switch to Japanese") == nil, "voice: Japanese removed")

// Offline name speller vs the content examples
do {
    let names = root.deletingLastPathComponent().appendingPathComponent("names")
    var hit = 0, total = 0
    struct Ex: Decodable { let name: String; let written: String }
    struct F: Decodable { let examples: [Ex] }
    for f in ["devanagari", "arabic", "cyrillic", "hebrew", "greek"] {
        guard let d = try? Data(contentsOf: names.appendingPathComponent("\(f).json")),
              let t = try? JSONDecoder().decode(NameTable.self, from: d), let ex = try? JSONDecoder().decode(F.self, from: d) else { continue }
        for e in ex.examples {
            total += 1
            if t.spell(e.name).folding(options: .diacriticInsensitive, locale: nil) == e.written.folding(options: .diacriticInsensitive, locale: nil) { hit += 1 }
        }
    }
    check(total == 0 || Double(hit) / Double(total) >= 0.7, "name speller matches \(hit)/\(total) content examples (≥70%)")
}

// Ink diff on synthetic 64x64 pages.
let side = InkDiff.side
func page(_ draw: (inout [UInt8]) -> Void) -> [UInt8] { var g = [UInt8](repeating: 230, count: side*side); draw(&g); return g }
func hline(_ g: inout [UInt8], y: Int, x0: Int, x1: Int, w: Int = 2) { for yy in y..<(y+w) { for x in x0..<x1 { g[yy*side+x] = 40 } } }
var ink = InkDiff()
let blank = page { _ in }
check(ink.process(gray: blank).strokeAdded == false, "first frame is the baseline")
check(ink.process(gray: blank).strokeAdded == false, "no change -> no stroke")
let one = page { hline(&$0, y: 20, x0: 10, x1: 50) }
check(ink.process(gray: one).strokeAdded, "one horizontal stroke -> stroke added")
check(ink.process(gray: one).strokeAdded == false, "same stroke again -> nothing new")
let jitter = page { hline(&$0, y: 21, x0: 11, x1: 51) }
check(ink.process(gray: jitter).strokeAdded == false, "1px jitter ignored")
let two = page { hline(&$0, y: 20, x0: 10, x1: 50); hline(&$0, y: 40, x0: 10, x1: 50) }
check(ink.process(gray: two).strokeAdded, "second stroke detected")
let dot = page { hline(&$0, y: 20, x0: 10, x1: 50); hline(&$0, y: 40, x0: 10, x1: 50); $0[60*side+60] = 40 }
check(ink.process(gray: dot).strokeAdded == false, "single speck ignored")
let hand = page { for i in 0..<(side*side/3) { $0[i] = 30 } }
let r = ink.process(gray: hand); check(r.unusable && !r.strokeAdded, "hand over box -> unusable, no advance")
let dark = [UInt8](repeating: 20, count: side*side)
check(ink.process(gray: dark).unusable, "dark frame unusable")
// thumbnail path from a real CGImage
let ctx = CGContext(data: nil, width: 400, height: 300, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)!
ctx.setFillColor(gray: 0.9, alpha: 1); ctx.fill(CGRect(x: 0, y: 0, width: 400, height: 300))
check(InkDiff.thumbnail(ctx.makeImage()!, box: CGRect(x: 0.2, y: 0.2, width: 0.6, height: 0.6))?.count == side*side, "CGImage thumbnail 64x64")
let t0 = Date(); var bench = InkDiff(); for _ in 0..<200 { _ = bench.process(gray: two); _ = bench.process(gray: one) }
let ms = Date().timeIntervalSince(t0) / 400 * 1000; check(ms < 2, String(format: "ink diff %.3f ms/frame", ms))

// Pacer
let t = Date(timeIntervalSince1970: 1000)
var p = Pacer(strokeCount: 3, now: t)
check(p.strokeWritten(.ink, now: t + 1) == [.showStroke(index: 2, of: 3, trigger: .ink)], "ink -> stroke 2")
check(p.tick(now: t + 3) == [], "no timeout at 2s")
check(p.tick(now: t + 5.1) == [.showStroke(index: 3, of: 3, trigger: .timeout)], "timeout after 4s -> stroke 3")
check(p.strokeWritten(.ink, now: t + 6) == [], "last stroke written -> wait to settle")
check(p.tick(now: t + 7.3) == [.finalize(trigger: .ink)], "settle -> finalize")
check(p.tick(now: t + 20) == [] && p.advance(.voice, now: t + 21) == [], "nothing after finalize")
var v = Pacer(strokeCount: 2, now: t)
check(v.advance(.voice, now: t) == [.showStroke(index: 2, of: 2, trigger: .voice)], "voice next")
check(v.advance(.voice, now: t) == [.finalize(trigger: .voice)], "voice check on last -> finalize")
var sl = Pacer(strokeCount: 2, now: t); sl.slower(now: t)
check(sl.tick(now: t + 5) == [] && sl.tick(now: t + 6.1) == [.showStroke(index: 2, of: 2, trigger: .timeout)], "slower -> 6s timeout")
var stuck = Pacer(strokeCount: 4, now: t); var acts = 0
for i in 1...40 { acts += stuck.tick(now: t + Double(i) * 0.5).count }
check(acts == 4, "no input at all still finishes (3 strokes + finalize), got \(acts)")
// StrokeTracker: a stroke is finished only after the ink stopped growing
var tr = StrokeTracker()
check(!tr.feed(strokeAdded: false, unusable: false) && !tr.feed(strokeAdded: false, unusable: false), "tracker: nothing written, nothing finished")
check(!tr.feed(strokeAdded: true, unusable: false) && tr.state == .writing, "tracker: ink arriving = still writing")
check(!tr.feed(strokeAdded: false, unusable: false), "tracker: one quiet frame is not enough")
check(!tr.feed(strokeAdded: true, unusable: false) && !tr.feed(strokeAdded: false, unusable: false), "tracker: more ink restarts the wait")
check(!tr.feed(strokeAdded: false, unusable: true) && !tr.feed(strokeAdded: false, unusable: false), "tracker: a hand in view resets the wait")
check(tr.feed(strokeAdded: false, unusable: false) && tr.state == .watching, "tracker: finished after two quiet usable frames")

print(fails == 0 ? "ALL PASS" : "\(fails) FAILED"); exit(fails == 0 ? 0 : 1)

enum ScriptInfo { static func isRTL(_ l: String) -> Bool { l == "arabic" || l == "hebrew" } }
