import SwiftUI

struct ChatView: View {
    @State private var inputText = ""
    @State private var messages: [ChatMessage] = [
        ChatMessage(role: .brain, text: "Hello. I'm your knowledge assistant. Ask me anything about your meetings, tasks, people, or decisions.", confidence: .high),
    ]

    var body: some View {
        VStack(spacing: 0) {
            // Messages
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 16) {
                        ForEach(messages) { msg in
                            MessageBubble(message: msg)
                                .id(msg.id)
                        }
                    }
                    .padding(20)
                }
                .onChange(of: messages.count) { _ in
                    if let last = messages.last {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }

            Divider()

            // Input bar
            HStack(spacing: 8) {
                // ReACT mode toggle
                Button(action: { useReACT.toggle() }) {
                    Image(systemName: useReACT ? "brain" : "magnifyingglass")
                        .font(.system(size: 13))
                        .foregroundColor(useReACT ? .accentColor : .secondary)
                }
                .buttonStyle(.plain)
                .frame(width: 28, height: 28)
                .help(useReACT ? "Deep reasoning mode (ReACT)" : "Simple search mode")

                TextField("Ask anything...", text: $inputText)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14))
                    .onSubmit { sendMessage() }

                Button(action: { sendMessage() }) {
                    Image(systemName: "paperplane")
                        .font(.system(size: 13))
                        .foregroundColor(inputText.isEmpty ? .secondary : .accentColor)
                }
                .buttonStyle(.plain)
                .disabled(inputText.isEmpty)
                .frame(width: 28, height: 28)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
    }

    @State private var useReACT = true

    private func sendMessage() {
        guard !inputText.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        let text = inputText
        inputText = ""

        messages.append(ChatMessage(role: .user, text: text))

        // Add thinking indicator
        let thinkingId = UUID()
        let thinkingText = useReACT ? "Reasoning and searching…" : "Searching knowledge base…"
        messages.append(ChatMessage(id: thinkingId, role: .brain, text: thinkingText, confidence: .medium))

        // Use ReACT agent for deeper reasoning, fallback to simple chat
        let endpoint = useReACT ? "http://127.0.0.1:8420/chat/react" : "http://127.0.0.1:8420/chat"
        let url = URL(string: endpoint)!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 180

        let body: [String: Any] = ["query": text, "offline": !useReACT]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)

        URLSession.shared.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                // Remove thinking message
                messages.removeAll { $0.id == thinkingId }

                if let error = error {
                    messages.append(ChatMessage(role: .brain, text: "Could not reach backend: \(error.localizedDescription)", confidence: .low))
                    return
                }

                guard let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let answer = json["answer"] as? String else {
                    messages.append(ChatMessage(role: .brain, text: "Failed to parse response from backend.", confidence: .low))
                    return
                }

                let confidenceStr = json["confidence"] as? String ?? "medium"
                let confidence: ChatMessage.Confidence = {
                    switch confidenceStr {
                    case "high": return .high
                    case "low": return .low
                    default: return .medium
                    }
                }()

                // Build source string
                var sourceText: String? = nil
                if let sources = json["sources"] as? [[String: Any]], !sources.isEmpty {
                    let sourceStrs = sources.compactMap { s -> String? in
                        guard let src = s["source"] as? String, let date = s["date"] as? String else { return nil }
                        let shortDate = String(date.prefix(10))
                        return "\(src), \(shortDate)"
                    }
                    if !sourceStrs.isEmpty {
                        sourceText = sourceStrs.joined(separator: " | ")
                    }
                }

                messages.append(ChatMessage(role: .brain, text: answer, confidence: confidence, source: sourceText))
            }
        }.resume()
    }
}

struct ChatMessage: Identifiable {
    let id: UUID
    let role: Role
    let text: String
    var confidence: Confidence = .high
    var source: String? = nil

    init(id: UUID = UUID(), role: Role, text: String, confidence: Confidence = .high, source: String? = nil) {
        self.id = id
        self.role = role
        self.text = text
        self.confidence = confidence
        self.source = source
    }

    enum Role { case user, brain }
    enum Confidence { case high, medium, low }
}

struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 60) }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                Text(message.text)
                    .font(.system(size: 14))
                    .lineSpacing(3)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(bubbleBackground)
                    .foregroundColor(message.role == .user ? .white : .primary)
                    .cornerRadius(12)

                if message.role == .brain {
                    HStack(spacing: 6) {
                        confidenceBadge
                        if let source = message.source {
                            Text(source)
                                .font(.system(size: 10))
                                .foregroundColor(.accentColor)
                        }
                    }
                }
            }

            if message.role == .brain { Spacer(minLength: 60) }
        }
    }

    private var bubbleBackground: Color {
        message.role == .user ? .accentColor : Color.secondary.opacity(0.15)
    }

    @ViewBuilder
    private var confidenceBadge: some View {
        switch message.confidence {
        case .high:
            Text("HIGH")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.green)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(.green.opacity(0.15))
                .cornerRadius(3)
        case .medium:
            Text("MEDIUM")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.orange)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(.orange.opacity(0.15))
                .cornerRadius(3)
        case .low:
            Text("LOW")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.secondary)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(.secondary.opacity(0.15))
                .cornerRadius(3)
        }
    }
}
