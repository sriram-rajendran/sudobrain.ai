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

                var sourceCards: [ChatSource] = []
                if let sources = json["sources"] as? [[String: Any]], !sources.isEmpty {
                    sourceCards = sources.compactMap { s -> ChatSource? in
                        guard let src = s["source"] as? String else { return nil }
                        let date = s["date"] as? String ?? ""
                        let shortDate = String(date.prefix(10))
                        let table = s["source_table"] as? String ?? ""
                        let sourceId = String(describing: s["source_id"] ?? "")
                        let excerpt = s["text"] as? String ?? ""
                        return ChatSource(source: src, date: shortDate, table: table, sourceId: sourceId, excerpt: excerpt)
                    }
                }

                messages.append(ChatMessage(role: .brain, text: answer, confidence: confidence, sources: sourceCards))
            }
        }.resume()
    }
}

struct ChatSource: Identifiable {
    let id = UUID()
    let source: String
    let date: String
    let table: String
    let sourceId: String
    let excerpt: String
}

struct ChatMessage: Identifiable {
    let id: UUID
    let role: Role
    let text: String
    var confidence: Confidence = .high
    var sources: [ChatSource] = []

    init(id: UUID = UUID(), role: Role, text: String, confidence: Confidence = .high, sources: [ChatSource] = []) {
        self.id = id
        self.role = role
        self.text = text
        self.confidence = confidence
        self.sources = sources
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
                    }

                    if !message.sources.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(message.sources.prefix(4)) { source in
                                CitationCard(source: source)
                            }
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

struct CitationCard: View {
    let source: ChatSource

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Image(systemName: iconName)
                    .font(.system(size: 10))
                    .foregroundColor(.accentColor)
                Text(source.source)
                    .font(.system(size: 10, weight: .medium))
                    .lineLimit(1)
                Spacer(minLength: 8)
                if !source.date.isEmpty {
                    Text(source.date)
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                }
            }
            if !source.excerpt.isEmpty {
                Text(source.excerpt)
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                    .lineLimit(2)
            }
            if !source.table.isEmpty || !source.sourceId.isEmpty {
                Text([source.table, source.sourceId].filter { !$0.isEmpty }.joined(separator: " #"))
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundColor(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: 420, alignment: .leading)
        .background(Color.secondary.opacity(0.08))
        .cornerRadius(6)
    }

    private var iconName: String {
        if source.table == "segments" { return "text.quote" }
        if source.table == "action_items" { return "checkmark.circle" }
        if source.table == "decisions" { return "arrow.triangle.branch" }
        if source.table == "promises" { return "hand.raised" }
        return "link"
    }
}
