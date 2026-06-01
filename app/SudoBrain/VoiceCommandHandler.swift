import Foundation
import Speech

/// Voice command handler — control SudoBrain by speaking.
/// Uses macOS Speech Recognition API (built-in, free).
class VoiceCommandHandler: ObservableObject {
    @Published var isListening: Bool = false
    @Published var lastCommand: String = ""
    @Published var lastResult: String = ""

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    /// Known command patterns
    private let commands: [(pattern: String, action: String)] = [
        ("what's on my plate", "briefing"),
        ("what do i have today", "briefing"),
        ("morning briefing", "briefing"),
        ("add a task", "add_task"),
        ("add task", "add_task"),
        ("add a reminder", "add_reminder"),
        ("remind me", "add_reminder"),
        ("what did", "search"),
        ("show me", "search"),
        ("who promised", "search_promises"),
        ("what promises", "search_promises"),
        ("start recording", "record_start"),
        ("stop recording", "record_stop"),
    ]

    /// Start listening for voice commands.
    func startListening() {
        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            lastResult = "Speech recognition not available"
            return
        }

        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let request = recognitionRequest else { return }

        request.shouldReportPartialResults = false

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            request.append(buffer)
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result, result.isFinal {
                let text = result.bestTranscription.formattedString
                DispatchQueue.main.async {
                    self.lastCommand = text
                    self.processCommand(text)
                    self.stopListening()
                }
            }
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
            isListening = true
        } catch {
            lastResult = "Failed to start: \(error.localizedDescription)"
        }
    }

    /// Stop listening.
    func stopListening() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        isListening = false
    }

    /// Match and execute a voice command.
    private func processCommand(_ text: String) {
        let lower = text.lowercased()

        for cmd in commands {
            if lower.contains(cmd.pattern) {
                executeAction(cmd.action, rawText: text)
                return
            }
        }

        // No match — treat as a chat query
        executeAction("chat", rawText: text)
    }

    /// Execute the matched action.
    private func executeAction(_ action: String, rawText: String) {
        switch action {
        case "briefing":
            callAPI("/briefing/morning") { result in
                self.lastResult = result
            }

        case "add_task":
            let taskText = rawText.replacingOccurrences(of: "add a task", with: "", options: .caseInsensitive)
                .replacingOccurrences(of: "add task", with: "", options: .caseInsensitive)
                .trimmingCharacters(in: .whitespaces)
            if !taskText.isEmpty {
                postAPI("/capture", body: ["text": "todo: \(taskText)"]) { result in
                    self.lastResult = "Task added: \(taskText)"
                }
            }

        case "add_reminder":
            let reminderText = rawText.replacingOccurrences(of: "remind me to", with: "", options: .caseInsensitive)
                .replacingOccurrences(of: "add a reminder", with: "", options: .caseInsensitive)
                .trimmingCharacters(in: .whitespaces)
            if !reminderText.isEmpty {
                postAPI("/capture", body: ["text": "remind: \(reminderText)"]) { result in
                    self.lastResult = "Reminder set: \(reminderText)"
                }
            }

        case "chat":
            postAPI("/chat", body: ["query": rawText]) { result in
                self.lastResult = result
            }

        default:
            lastResult = "Command not recognized: \(rawText)"
        }
    }

    private func callAPI(_ path: String, completion: @escaping (String) -> Void) {
        guard let url = URL(string: "http://127.0.0.1:8420\(path)") else { return }
        URLSession.shared.dataTask(with: url) { data, _, error in
            DispatchQueue.main.async {
                if let data = data, let str = String(data: data, encoding: .utf8) {
                    completion(str)
                } else {
                    completion("Error: \(error?.localizedDescription ?? "unknown")")
                }
            }
        }.resume()
    }

    private func postAPI(_ path: String, body: [String: String], completion: @escaping (String) -> Void) {
        guard let url = URL(string: "http://127.0.0.1:8420\(path)") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { data, _, error in
            DispatchQueue.main.async {
                if let data = data,
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let answer = json["answer"] as? String ?? json["text"] as? String {
                    completion(answer)
                } else {
                    completion("Done")
                }
            }
        }.resume()
    }
}
