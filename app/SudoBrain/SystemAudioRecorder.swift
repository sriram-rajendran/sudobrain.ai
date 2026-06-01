import ScreenCaptureKit
import AVFoundation
import Foundation

class SystemAudioRecorder: NSObject, SCStreamDelegate {
    private var stream: SCStream?
    private var outputHandler: SystemAudioOutput?
    private(set) var isCapturing = false

    static func checkPermission() -> Bool {
        CGPreflightScreenCaptureAccess()
    }

    /// Start capture using async/await. Must be called from a Task.
    func startCapture(outputURL: URL) async throws {
        // Skip CGPreflightScreenCaptureAccess check — it returns false for ad-hoc signed apps
        // even when permission is granted. Just try to capture and handle errors.

        let debugPath = outputURL.deletingLastPathComponent().appendingPathComponent("sysaudio_debug.log")
        try? "startCapture called\n".write(to: debugPath, atomically: true, encoding: .utf8)

        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        } catch {
            try? "SCShareableContent failed: \(error.localizedDescription)\n".write(to: debugPath, atomically: true, encoding: .utf8)
            throw error
        }

        try? "Got content: \(content.displays.count) displays\n".write(to: debugPath, atomically: true, encoding: .utf8)

        guard let display = content.displays.first else {
            throw NSError(domain: "SudoBrain", code: 2, userInfo: [NSLocalizedDescriptionKey: "No display."])
        }

        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.showsCursor = false
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.channelCount = 1
        config.sampleRate = 48000

        let handler = SystemAudioOutput(outputURL: outputURL)
        self.outputHandler = handler

        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        self.stream = stream

        try stream.addStreamOutput(handler, type: .audio, sampleHandlerQueue: DispatchQueue(label: "com.sudobrain.systemaudio", qos: .userInteractive))

        try await stream.startCapture()
        self.isCapturing = true

        try? "Capture started successfully\n".write(to: debugPath, atomically: true, encoding: .utf8)
    }

    func stopCapture() {
        guard isCapturing, let stream = stream else { return }

        stream.stopCapture { _ in }
        outputHandler?.close()

        self.stream = nil
        self.outputHandler = nil
        self.isCapturing = false
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        self.isCapturing = false
    }
}

private class SystemAudioOutput: NSObject, SCStreamOutput {
    private let outputURL: URL
    private var fileHandle: FileHandle?
    var frameCount: Int = 0

    init(outputURL: URL) {
        self.outputURL = outputURL
        super.init()
        FileManager.default.createFile(atPath: outputURL.path, contents: nil)
        fileHandle = FileHandle(forWritingAtPath: outputURL.path)
        writeWAVHeader(dataSize: 0)
    }

    func close() {
        guard let fh = fileHandle else { return }
        let dataSize = UInt32(frameCount * 4)
        fh.seek(toFileOffset: 0)
        writeWAVHeader(dataSize: dataSize)
        fh.closeFile()
        fileHandle = nil
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid, sampleBuffer.numSamples > 0 else { return }
        guard let fh = fileHandle else { return }
        guard let blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer) else { return }

        var totalLength = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil,
                                           totalLengthOut: &totalLength, dataPointerOut: &dataPointer) == kCMBlockBufferNoErr,
              let data = dataPointer, totalLength > 0 else { return }

        fh.write(Data(bytes: data, count: totalLength))
        frameCount += sampleBuffer.numSamples
    }

    private func writeWAVHeader(dataSize: UInt32) {
        guard let fh = fileHandle else { return }
        let sr: UInt32 = 48000
        let ch: UInt16 = 1
        let bps: UInt16 = 32
        let byteRate = sr * UInt32(ch) * UInt32(bps / 8)
        let blockAlign = ch * (bps / 8)

        var h = Data()
        h.append(contentsOf: "RIFF".utf8)
        h.append(contentsOf: withUnsafeBytes(of: (36 + dataSize).littleEndian) { Array($0) })
        h.append(contentsOf: "WAVE".utf8)
        h.append(contentsOf: "fmt ".utf8)
        h.append(contentsOf: withUnsafeBytes(of: UInt32(16).littleEndian) { Array($0) })
        h.append(contentsOf: withUnsafeBytes(of: UInt16(3).littleEndian) { Array($0) }) // IEEE float
        h.append(contentsOf: withUnsafeBytes(of: ch.littleEndian) { Array($0) })
        h.append(contentsOf: withUnsafeBytes(of: sr.littleEndian) { Array($0) })
        h.append(contentsOf: withUnsafeBytes(of: byteRate.littleEndian) { Array($0) })
        h.append(contentsOf: withUnsafeBytes(of: blockAlign.littleEndian) { Array($0) })
        h.append(contentsOf: withUnsafeBytes(of: bps.littleEndian) { Array($0) })
        h.append(contentsOf: "data".utf8)
        h.append(contentsOf: withUnsafeBytes(of: dataSize.littleEndian) { Array($0) })
        fh.write(h)
    }
}
