import AVFoundation
import CoreImage
import Foundation
import Observation
#if canImport(UIKit)
import UIKit
#endif

/// Phone camera as a frame source: keeps the latest frame so the pacer can sample it every second.
@MainActor
@Observable
final class PhoneCamera {
    enum State: Equatable { case off, starting, running, unauthorized, unavailable }
    private(set) var state: State = .off

    let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "worn.camera")
    private let sink = FrameSink()
    private var configured = false

    /// Simulator / no-camera stand-in: a page that gets one more stroke each time `simulatedPen` advances.
    let simulated = SimulatedPage()

    var usesSimulatedPage: Bool { state == .unavailable }

    func start() async {
        guard state != .running else { return }
        #if targetEnvironment(simulator)
        state = .unavailable
        return
        #else
        state = .starting
        let ok = await AVCaptureDevice.requestAccess(for: .video)
        guard ok else { state = .unauthorized; return }
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: device) else { state = .unavailable; return }
        let session = self.session, output = self.output, queue = self.queue, sink = self.sink
        let needsConfig = !configured
        configured = true
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            queue.async {
                if needsConfig {
                    session.beginConfiguration()
                    session.sessionPreset = .hd1280x720
                    if session.canAddInput(input) { session.addInput(input) }
                    output.alwaysDiscardsLateVideoFrames = true
                    output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
                    output.setSampleBufferDelegate(sink, queue: queue)
                    if session.canAddOutput(output) { session.addOutput(output) }
                    if let conn = output.connection(with: .video), conn.isVideoRotationAngleSupported(90) {
                        conn.videoRotationAngle = 90   // portrait frames
                    }
                    session.commitConfiguration()
                }
                session.startRunning()
                c.resume()
            }
        }
        state = .running
        #endif
    }

    func stop() {
        let session = self.session
        queue.async { if session.isRunning { session.stopRunning() } }
        if state == .running { state = .off }
    }

    /// Latest frame (or the simulated page).
    func frame() -> CGImage? {
        if usesSimulatedPage { return simulated.render() }
        return sink.latest()
    }

    func jpeg(quality: CGFloat = 0.8) -> Data? {
        guard let img = frame() else { return nil }
        return Self.jpeg(img, quality: quality)
    }

    static func jpeg(_ img: CGImage, quality: CGFloat = 0.8) -> Data? {
        #if canImport(UIKit)
        return UIImage(cgImage: img).jpegData(compressionQuality: quality)
        #else
        return nil
        #endif
    }
}

/// Receives camera frames off the main thread and keeps only the newest one.
private final class FrameSink: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var buffer: CVPixelBuffer?
    private let context = CIContext(options: [.cacheIntermediates: false])

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let px = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lock.lock(); buffer = px; lock.unlock()
    }

    func latest() -> CGImage? {
        lock.lock(); let px = buffer; lock.unlock()
        guard let px else { return nil }
        let ci = CIImage(cvPixelBuffer: px)
        return context.createCGImage(ci, from: ci.extent)
    }
}

/// A sheet of paper drawn in code, with the first `strokesDrawn` strokes of a character in pen.
/// Lets the whole auto-pacing loop run (and be demoed) where there's no camera.
@MainActor
final class SimulatedPage {
    var strokes: StrokeData?
    var glyph: String = ""
    var strokesDrawn = 0

    func reset(strokes: StrokeData?, glyph: String) {
        self.strokes = strokes; self.glyph = glyph; strokesDrawn = 0
    }

    func render(size: CGSize = CGSize(width: 720, height: 960)) -> CGImage? {
        guard let ctx = CGContext(data: nil, width: Int(size.width), height: Int(size.height), bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        // CoreGraphics is y-up; flip so stroke data (y-down) draws upright.
        ctx.translateBy(x: 0, y: size.height); ctx.scaleBy(x: 1, y: -1)
        ctx.setFillColor(CGColor(red: 0.96, green: 0.94, blue: 0.89, alpha: 1))
        ctx.fill(CGRect(origin: .zero, size: size))
        let box = CGRect(x: size.width * 0.2, y: size.height * 0.2, width: size.width * 0.6, height: size.height * 0.6)
        let side = min(box.width, box.height)
        let square = CGRect(x: box.midX - side / 2, y: box.midY - side / 2, width: side, height: side).insetBy(dx: side * 0.08, dy: side * 0.08)
        ctx.setStrokeColor(CGColor(red: 0.12, green: 0.12, blue: 0.16, alpha: 1))
        ctx.setLineWidth(side * 0.045)
        ctx.setLineCap(.round); ctx.setLineJoin(.round)
        if let strokes {
            for s in strokes.strokes.prefix(strokesDrawn) {
                ctx.addPath(s.centerline.cgPath(in: square))
                ctx.strokePath()
            }
        } else if strokesDrawn > 0 {
            // No stroke data: one bar per "stroke" so ink still appears.
            for i in 0..<strokesDrawn {
                let y = square.minY + CGFloat(i + 1) * square.height / 8
                ctx.move(to: CGPoint(x: square.minX, y: y)); ctx.addLine(to: CGPoint(x: square.maxX, y: y))
            }
            ctx.strokePath()
        }
        return ctx.makeImage()
    }
}
