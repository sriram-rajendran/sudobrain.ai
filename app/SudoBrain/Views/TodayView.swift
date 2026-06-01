import SwiftUI

struct TodayView: View {
    @ObservedObject var recorder: AudioRecorder
    @State private var tasks: [[String: Any]] = []
    @State private var promises: [[String: Any]] = []
    @State private var briefing: String = ""
    @State private var isLoading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Greeting
                VStack(alignment: .leading, spacing: 4) {
                    Text("Good morning")
                        .font(.system(size: 28, weight: .bold))
                    Text(Date(), format: .dateTime.weekday(.wide).month(.wide).day().year())
                        .font(.system(size: 15))
                        .foregroundColor(.secondary)
                }

                // Tasks Card
                if !tasks.isEmpty {
                    CardView(title: "Pending Tasks", icon: "checkmark.circle", action: "See all \(tasks.count)") {
                        ForEach(tasks.prefix(5).indices, id: \.self) { i in
                            let t = tasks[i]
                            HStack(spacing: 10) {
                                Circle()
                                    .strokeBorder(Color.secondary.opacity(0.3), lineWidth: 1.5)
                                    .frame(width: 16, height: 16)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(t["text"] as? String ?? "")
                                        .font(.system(size: 13))
                                    if let assignee = t["assignee"] as? String, !assignee.isEmpty {
                                        Text(assignee)
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                            .padding(.horizontal, 5)
                                            .padding(.vertical, 1)
                                            .background(.quaternary)
                                            .cornerRadius(3)
                                    }
                                }
                                Spacer()
                                if let due = t["due_date"] as? String, !due.isEmpty {
                                    Text(due)
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundColor(isOverdue(due) ? .orange : .secondary)
                                }
                            }
                            .padding(.vertical, 3)
                        }
                    }
                }

                // Promises Card
                if !promises.isEmpty {
                    CardView(title: "Open Promises", icon: "handshake", action: "See all") {
                        ForEach(promises.indices, id: \.self) { i in
                            let p = promises[i]
                            HStack(spacing: 10) {
                                Circle()
                                    .fill(.orange)
                                    .frame(width: 6, height: 6)
                                Text("\(p["promised_by_name"] as? String ?? "") -> \(p["promised_to_name"] as? String ?? ""):")
                                    .font(.system(size: 13, weight: .medium))
                                Text(p["description"] as? String ?? "")
                                    .font(.system(size: 13))
                                Spacer()
                                if let due = p["due_date"] as? String {
                                    Text(due)
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundColor(.orange)
                                }
                            }
                            .padding(.vertical, 3)
                        }
                    }
                }

                // Briefing / Insight
                if !briefing.isEmpty {
                    InsightCard(text: briefing)
                }

                // Loading state
                if isLoading {
                    HStack {
                        ProgressView().scaleEffect(0.7)
                        Text("Loading your day...")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                }

                // Empty state
                if !isLoading && tasks.isEmpty && promises.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "checkmark.seal")
                            .font(.system(size: 28))
                            .foregroundColor(.green.opacity(0.5))
                        Text("All clear")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundColor(.secondary)
                        Text("No pending tasks or promises. Record a meeting to get started.")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary.opacity(0.6))
                            .multilineTextAlignment(.center)
                    }
                    .padding(.vertical, 40)
                    .frame(maxWidth: .infinity)
                }

                // Recent recordings
                if !recorder.recordingHistory.isEmpty {
                    CardView(title: "Recent Recordings", icon: "waveform") {
                        ForEach(recorder.recordingHistory.prefix(3)) { entry in
                            HStack(spacing: 8) {
                                Image(systemName: entry.mode == .voiceNote ? "mic" : "person.3")
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                                    .frame(width: 16)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(entry.mode == .voiceNote ? "Voice Note" : "Meeting")
                                        .font(.system(size: 13, weight: .medium))
                                    if let transcript = entry.transcript, !transcript.isEmpty {
                                        Text(transcript)
                                            .font(.system(size: 11))
                                            .foregroundColor(.secondary)
                                            .lineLimit(1)
                                    }
                                }
                                Spacer()
                                Text(entry.date, format: .dateTime.hour().minute())
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }
            }
            .padding(28)
        }
        .frame(maxWidth: 720)
        .task { await loadData() }
    }

    private func loadData() async {
        isLoading = true
        async let t = APIClient.shared.getRaw("/action-items")
        async let p = APIClient.shared.getRaw("/promises")

        tasks = (try? await t) ?? []
        promises = (try? await p) ?? []
        isLoading = false

        // Load briefing in background (slower — uses local reasoning engine)
        Task {
            if let b = try? await APIClient.shared.getRawObject("/briefing/morning") {
                briefing = b["content"] as? String ?? ""
            }
        }
    }

    private func isOverdue(_ dateStr: String) -> Bool {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: dateStr) else { return false }
        return date < Date()
    }
}

// MARK: - Reusable Components

struct CardView<Content: View>: View {
    let title: String
    let icon: String
    var action: String? = nil
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                HStack(spacing: 6) {
                    Image(systemName: icon)
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                    Text(title)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.secondary)
                        .textCase(.uppercase)
                }
                Spacer()
                if let action = action {
                    Button(action) {}
                        .font(.system(size: 11))
                        .buttonStyle(.plain)
                        .foregroundColor(.accentColor)
                }
            }
            content()
        }
        .padding(14)
        .background(.quaternary.opacity(0.5))
        .cornerRadius(10)
    }
}

struct InsightCard: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Rectangle()
                .fill(.blue)
                .frame(width: 3)
                .cornerRadius(2)
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 4) {
                    Image(systemName: "brain")
                        .font(.system(size: 11))
                    Text("Morning Briefing")
                        .font(.system(size: 10, weight: .semibold))
                        .textCase(.uppercase)
                }
                .foregroundColor(.blue)
                Text(text)
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)
                    .lineSpacing(3)
            }
        }
        .padding(14)
        .background(.quaternary.opacity(0.5))
        .cornerRadius(10)
    }
}
