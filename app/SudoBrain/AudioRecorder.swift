import AVFoundation
import Foundation

/// Core audio recorder with mic capture (voice notes) and system audio capture (meetings).
class AudioRecorder: ObservableObject {
    @Published var isRecording = false
    @Published var recordingDuration: TimeInterval = 0
    @Published var audioLevel: Float = 0
    @Published var currentMode: RecordingMode = .voiceNote
    @Published var lastRecordingPath: String?
    @Published var errorMessage: String?
    @Published var processingStatus: ProcessingStatus = .idle
    @Published var recordingHistory: [RecordingEntry] = []

    private var audioEngine: AVAudioEngine?
    private var audioFile: AVAudioFile?
    private var systemRecorder: SystemAudioRecorder?
    private var timer: Timer?
    private var recordingStartTime: Date?
    private var currentFolderURL: URL?

    enum RecordingMode: String, CaseIterable {
        case voiceNote = "voice_note"
        case meeting = "meeting"
    }

    enum ProcessingStatus: Equatable {
        case idle
        case recording
        case sending
        case processing
        case completed(String) // transcript preview
        case failed(String)   // error message
    }

    struct RecordingEntry: Identifiable {
        let id: String
        let date: Date
        let mode: RecordingMode
        let modeLabel: String
        let duration: TimeInterval
        let path: String
        var status: ProcessingStatus
        var transcript: String?
    }

    private var recordingsDir: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = docs.appendingPathComponent("SudoBrain/recordings")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    // MARK: - Permissions

    func checkMicrophonePermission() -> Bool {
        return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    func requestMicrophonePermission(completion: @escaping (Bool) -> Void) {
        AVCaptureDevice.requestAccess(for: .audio, completionHandler: completion)
    }

    // MARK: - Recording

    func startRecording() {
        guard checkMicrophonePermission() else {
            requestMicrophonePermission { [weak self] granted in
                DispatchQueue.main.async {
                    if granted {
                        self?.startRecording()
                    } else {
                        self?.errorMessage = "Microphone permission denied. Enable in System Settings."
                    }
                }
            }
            return
        }

        do {
            let timestamp = Self.dateFormatter.string(from: Date())
            let folderName = "\(timestamp)_\(currentMode.rawValue)"
            let folderURL = recordingsDir.appendingPathComponent(folderName)
            try FileManager.default.createDirectory(at: folderURL, withIntermediateDirectories: true)
            currentFolderURL = folderURL

            let micURL = folderURL.appendingPathComponent("recording.wav")

            // Start mic recording
            try startMicCapture(outputURL: micURL)

            // Start system audio capture in meeting mode
            // Write debug log to file since NSLog is suppressed
            let debugLog = "Mode: \(currentMode.rawValue), Folder: \(folderURL.path)\n"
            try? debugLog.write(to: folderURL.appendingPathComponent("debug.log"), atomically: true, encoding: .utf8)

            if currentMode == .meeting {
                let systemURL = folderURL.appendingPathComponent("system_audio.wav")
                try? "Starting system audio\n".write(to: folderURL.appendingPathComponent("debug.log"), atomically: true, encoding: .utf8)
                let recorder = SystemAudioRecorder()
                self.systemRecorder = recorder
                Task.detached {
                    do {
                        try await recorder.startCapture(outputURL: systemURL)
                        try? "System audio started OK\n".write(to: folderURL.appendingPathComponent("debug.log"), atomically: true, encoding: .utf8)
                    } catch {
                        try? "System audio FAILED: \(error.localizedDescription)\n".write(to: folderURL.appendingPathComponent("debug.log"), atomically: true, encoding: .utf8)
                    }
                }
            }

            // Save metadata
            let metadata: [String: Any] = [
                "id": UUID().uuidString,
                "mode": currentMode.rawValue,
                "created_at": ISO8601DateFormatter().string(from: Date()),
                "sample_rate": 48000,
                "channels": 1,
                "has_system_audio": currentMode == .meeting,
                "status": "recording",
            ]
            let metadataURL = folderURL.appendingPathComponent("metadata.json")
            let jsonData = try JSONSerialization.data(withJSONObject: metadata, options: .prettyPrinted)
            try jsonData.write(to: metadataURL)

            // Start timer
            recordingStartTime = Date()
            timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                guard let start = self?.recordingStartTime else { return }
                self?.recordingDuration = Date().timeIntervalSince(start)
            }

            DispatchQueue.main.async {
                self.isRecording = true
                self.lastRecordingPath = micURL.path
                self.processingStatus = .recording
                self.errorMessage = nil
            }

            print("[SudoBrain] Recording started: \(micURL.path)")

        } catch {
            DispatchQueue.main.async {
                self.errorMessage = "Failed to start: \(error.localizedDescription)"
                self.processingStatus = .failed(error.localizedDescription)
            }
        }
    }

    func stopRecording() {
        // Stop mic
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
        audioFile = nil

        // Stop system audio
        if let recorder = systemRecorder {
            recorder.stopCapture()
            systemRecorder = nil
        }

        timer?.invalidate()
        timer = nil

        let duration = recordingDuration

        DispatchQueue.main.async {
            self.isRecording = false
            self.audioLevel = 0
            self.processingStatus = .sending
        }

        // Add to history
        if let path = lastRecordingPath {
            let entryID = UUID().uuidString
            let entryMode = currentMode
            let entry = RecordingEntry(
                id: entryID,
                date: Date(),
                mode: entryMode,
                modeLabel: Self.modeLabel(entryMode.rawValue),
                duration: duration,
                path: path,
                status: .sending
            )
            DispatchQueue.main.async {
                self.recordingHistory.insert(entry, at: 0)
                if self.recordingHistory.count > 20 {
                    self.recordingHistory = Array(self.recordingHistory.prefix(20))
                }
            }
            processRecording(audioPath: path, mode: entryMode, historyID: entryID)
        }

        print("[SudoBrain] Recording stopped. Duration: \(String(format: "%.1f", duration))s")
    }

    // MARK: - Mic Capture

    private func startMicCapture(outputURL: URL) throws {
        let engine = AVAudioEngine()
        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        let recordingFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: inputFormat.sampleRate,
            channels: 1,
            interleaved: false
        )!

        audioFile = try AVAudioFile(forWriting: outputURL, settings: recordingFormat.settings)

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: recordingFormat) { [weak self] buffer, _ in
            guard let self = self else { return }
            try? self.audioFile?.write(from: buffer)

            let level = self.calculateLevel(buffer: buffer)
            DispatchQueue.main.async {
                self.audioLevel = level
            }
        }

        try engine.start()
        audioEngine = engine
    }

    // MARK: - Audio Level

    private func calculateLevel(buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData?[0] else { return 0 }
        let frames = Int(buffer.frameLength)
        var sum: Float = 0
        for i in 0..<frames {
            sum += channelData[i] * channelData[i]
        }
        let rms = sqrt(sum / Float(max(frames, 1)))
        return min(1.0, rms * 5.0)
    }

    // MARK: - Backend Communication

    private func processRecording(audioPath: String, mode: RecordingMode, historyID: String) {
        let url = URL(string: "http://127.0.0.1:8420/process")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120

        let body: [String: Any] = [
            "audio_path": audioPath,
            "mode": mode.rawValue,
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        DispatchQueue.main.async {
            self.processingStatus = .processing
        }

        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self = self else { return }

            if let error = error {
                let msg = error.localizedDescription
                print("[SudoBrain] Backend failed: \(msg)")
                DispatchQueue.main.async {
                    self.processingStatus = .failed(msg)
                    if let index = self.recordingHistory.firstIndex(where: { $0.id == historyID }) {
                        self.recordingHistory[index].status = .failed(msg)
                    }
                }
                return
            }

            if let data = data {
                let resultStr = String(data: data, encoding: .utf8) ?? ""

                // Parse transcript preview
                var preview = ""
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    preview = json["transcript_preview"] as? String ?? ""
                }

                print("[SudoBrain] Processing complete: \(resultStr.prefix(100))")
                DispatchQueue.main.async {
                    self.processingStatus = .completed(String(preview.prefix(100)))
                    if let index = self.recordingHistory.firstIndex(where: { $0.id == historyID }) {
                        self.recordingHistory[index].status = .completed(String(preview.prefix(100)))
                        self.recordingHistory[index].transcript = preview
                    }
                }
                self.loadRecentRecordings()
            }
        }.resume()
    }

    func loadRecentRecordings(limit: Int = 5) {
        guard let url = URL(string: "http://127.0.0.1:8420/recordings?limit=\(limit)") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 10

        URLSession.shared.dataTask(with: request) { [weak self] data, _, error in
            guard let self = self, let data = data, error == nil else { return }
            guard let rows = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }

            let entries = rows.compactMap { Self.recordingEntry(from: $0) }
            DispatchQueue.main.async {
                let localActive = self.recordingHistory.filter {
                    switch $0.status {
                    case .sending, .processing, .recording:
                        return true
                    default:
                        return false
                    }
                }
                let remoteIDs = Set(entries.map(\.id))
                let retainedLocal = localActive.filter { !remoteIDs.contains($0.id) }
                self.recordingHistory = Array((retainedLocal + entries).prefix(20))
            }
        }.resume()
    }

    // MARK: - Helpers

    private static func recordingEntry(from row: [String: Any]) -> RecordingEntry? {
        guard let id = row["id"] as? String else { return nil }
        let modeRaw = row["mode"] as? String ?? RecordingMode.voiceNote.rawValue
        let mode = RecordingMode(rawValue: modeRaw) ?? .meeting
        let statusRaw = row["status"] as? String ?? "recorded"
        let preview = row["full_text"] as? String

        return RecordingEntry(
            id: id,
            date: parseBackendDate(row["created_at"] as? String),
            mode: mode,
            modeLabel: modeLabel(modeRaw),
            duration: row["duration_seconds"] as? Double ?? 0,
            path: row["audio_path"] as? String ?? "",
            status: processingStatus(statusRaw, preview: preview),
            transcript: preview
        )
    }

    private static func processingStatus(_ raw: String, preview: String?) -> ProcessingStatus {
        switch raw {
        case "completed":
            return .completed(String((preview ?? "").prefix(100)))
        case "failed":
            return .failed("Processing failed")
        case "processing":
            return .processing
        case "recording":
            return .recording
        default:
            return .idle
        }
    }

    private static func modeLabel(_ raw: String) -> String {
        switch raw {
        case RecordingMode.voiceNote.rawValue:
            return "Voice Note"
        case RecordingMode.meeting.rawValue:
            return "Meeting"
        case "fathom_meeting":
            return "Fathom"
        case "slack_batch":
            return "Slack"
        case "gmail_batch":
            return "Gmail"
        case "linear_batch":
            return "Linear"
        case "document":
            return "Document"
        default:
            return raw.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    private static func parseBackendDate(_ raw: String?) -> Date {
        guard let raw else { return Date() }
        let trimmed = String(raw.prefix(19))
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter.date(from: trimmed) ?? Date()
    }

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd_HH-mm-ss"
        return f
    }()
}
