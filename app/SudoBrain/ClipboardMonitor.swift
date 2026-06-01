import Cocoa
import Foundation

/// Clipboard intelligence — monitors clipboard for content worth capturing.
/// Offers to save relevant clipboard content to SudoBrain.
class ClipboardMonitor: ObservableObject {
    @Published var isMonitoring: Bool = false
    @Published var lastCapture: String = ""
    @Published var suggestion: ClipboardSuggestion?

    private var timer: Timer?
    private var lastChangeCount: Int = 0

    struct ClipboardSuggestion: Identifiable {
        let id = UUID()
        let text: String
        let suggestedType: String  // "task", "idea", "decision", "person"
        let suggestedAction: String
    }

    /// Start monitoring clipboard changes.
    func start() {
        lastChangeCount = NSPasteboard.general.changeCount
        isMonitoring = true

        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            self?.checkClipboard()
        }
    }

    /// Stop monitoring.
    func stop() {
        timer?.invalidate()
        timer = nil
        isMonitoring = false
    }

    private func checkClipboard() {
        let current = NSPasteboard.general.changeCount
        guard current != lastChangeCount else { return }
        lastChangeCount = current

        guard let text = NSPasteboard.general.string(forType: .string),
              !text.isEmpty, text.count >= 10, text.count <= 2000 else { return }

        // Classify the clipboard content
        let suggestion = classifyContent(text)
        if let suggestion = suggestion {
            DispatchQueue.main.async {
                self.lastCapture = text
                self.suggestion = suggestion
            }
        }
    }

    /// Classify clipboard text and suggest an action.
    private func classifyContent(_ text: String) -> ClipboardSuggestion? {
        let lower = text.lowercased()

        // Task patterns
        let taskPatterns = ["todo", "need to", "action item", "follow up", "deadline",
                           "by friday", "by monday", "by end of", "must", "should"]
        for p in taskPatterns {
            if lower.contains(p) {
                return ClipboardSuggestion(
                    text: text,
                    suggestedType: "task",
                    suggestedAction: "Save as task?"
                )
            }
        }

        // Decision patterns
        let decisionPatterns = ["decided", "decision", "we agreed", "approved", "rejected",
                               "going with", "will use", "chose"]
        for p in decisionPatterns {
            if lower.contains(p) {
                return ClipboardSuggestion(
                    text: text,
                    suggestedType: "decision",
                    suggestedAction: "Save as decision?"
                )
            }
        }

        // Promise patterns
        let promisePatterns = ["i will", "i'll", "promise", "committed to", "guarantee"]
        for p in promisePatterns {
            if lower.contains(p) {
                return ClipboardSuggestion(
                    text: text,
                    suggestedType: "promise",
                    suggestedAction: "Save as promise?"
                )
            }
        }

        // Idea patterns
        let ideaPatterns = ["what if", "idea", "could we", "maybe we should", "interesting",
                           "thought about", "brainstorm"]
        for p in ideaPatterns {
            if lower.contains(p) {
                return ClipboardSuggestion(
                    text: text,
                    suggestedType: "idea",
                    suggestedAction: "Save as idea?"
                )
            }
        }

        // Only suggest for text that looks meaningful (has multiple words)
        let wordCount = text.split(separator: " ").count
        if wordCount >= 5 {
            return ClipboardSuggestion(
                text: text,
                suggestedType: "idea",
                suggestedAction: "Capture this?"
            )
        }

        return nil
    }

    /// Save the suggested clipboard content to SudoBrain.
    func acceptSuggestion() {
        guard let suggestion = suggestion else { return }

        let prefix: String
        switch suggestion.suggestedType {
        case "task": prefix = "todo:"
        case "idea": prefix = "idea:"
        case "decision": prefix = "idea:"  // decisions need more context
        default: prefix = ""
        }

        let body = ["text": "\(prefix) \(suggestion.text)"]

        guard let url = URL(string: "http://127.0.0.1:8420/capture") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { _, _, _ in
            DispatchQueue.main.async {
                self.suggestion = nil
            }
        }.resume()
    }

    /// Dismiss the suggestion.
    func dismissSuggestion() {
        suggestion = nil
    }
}
