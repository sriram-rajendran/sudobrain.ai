import Foundation
import Speech
import AVFoundation

/// Live transcription using macOS Speech Recognition framework.
/// Shows words as they're spoken in real-time.
class LiveTranscriber: ObservableObject {
    @Published var transcript: String = ""
    @Published var isTranscribing: Bool = false
    @Published var error: String?

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    /// Request speech recognition permission.
    func requestPermission(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            DispatchQueue.main.async {
                switch status {
                case .authorized:
                    completion(true)
                default:
                    self.error = "Speech recognition not authorized"
                    completion(false)
                }
            }
        }
    }

    /// Start live transcription from microphone.
    func start() {
        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            error = "Speech recognizer not available"
            return
        }

        // Reset state
        transcript = ""
        error = nil

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let request = recognitionRequest else { return }

        request.shouldReportPartialResults = true
        request.taskHint = .dictation

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            request.append(buffer)
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result {
                DispatchQueue.main.async {
                    self.transcript = result.bestTranscription.formattedString

                    // Detect promises and action items in real-time
                    self.detectLiveInsights(result.bestTranscription.formattedString)
                }
            }

            if let error = error {
                DispatchQueue.main.async {
                    self.error = error.localizedDescription
                    self.stop()
                }
            }
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
            isTranscribing = true
        } catch {
            self.error = "Audio engine failed to start: \(error.localizedDescription)"
        }
    }

    /// Stop live transcription.
    func stop() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        isTranscribing = false
    }

    /// Detect promises and action items in live text.
    private func detectLiveInsights(_ text: String) {
        let lower = text.lowercased()
        let promisePatterns = ["i will", "i'll", "i promise", "i'll send", "i'll email", "i'll share",
                               "let me", "i'll get back", "i'll follow up"]
        let actionPatterns = ["need to", "should", "have to", "must", "action item",
                              "by friday", "by monday", "by end of", "deadline"]

        for pattern in promisePatterns {
            if lower.contains(pattern) {
                // Could send notification to Swift UI here
                break
            }
        }
    }
}
