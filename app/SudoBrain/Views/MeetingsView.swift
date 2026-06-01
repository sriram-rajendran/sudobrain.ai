import SwiftUI

struct MeetingsView: View {
    @State private var recordings: [[String: Any]] = []
    @State private var selectedId: String?
    @State private var selectedTranscript: String = ""
    @State private var isLoading = true

    var meetingRecordings: [[String: Any]] {
        recordings.filter { ($0["mode"] as? String) == "meeting" && ($0["status"] as? String) == "completed" }
    }

    var body: some View {
        HSplitView {
            // Recording list
            VStack(alignment: .leading, spacing: 0) {
                Text("Meetings")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(.secondary)
                    .textCase(.uppercase)
                    .padding(.horizontal, 12)
                    .padding(.top, 10)
                    .padding(.bottom, 6)

                if isLoading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if recordings.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "person.3")
                            .font(.system(size: 24))
                            .foregroundColor(.secondary.opacity(0.4))
                        Text("No recordings yet")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(selection: $selectedId) {
                        ForEach(recordings.indices, id: \.self) { i in
                            let r = recordings[i]
                            let id = r["id"] as? String ?? "\(i)"
                            RecordingRow(recording: r)
                                .tag(id)
                        }
                    }
                    .listStyle(.sidebar)
                    .onChange(of: selectedId) { newValue in
                        if let id = newValue { loadTranscript(id: id) }
                    }
                }
            }
            .frame(minWidth: 220, maxWidth: 280)

            // Detail
            if let id = selectedId, let recording = recordings.first(where: { ($0["id"] as? String) == id }) {
                RecordingDetailView(recording: recording, transcript: selectedTranscript)
            } else {
                PlaceholderView(title: "Select a recording", subtitle: "Choose from the list to view transcript")
            }
        }
        .task { await loadRecordings() }
    }

    private func loadRecordings() async {
        isLoading = true
        recordings = (try? await APIClient.shared.getRaw("/recordings?limit=50")) ?? []
        isLoading = false
    }

    private func loadTranscript(id: String) {
        Task {
            if let data = try? await APIClient.shared.getRawObject("/transcript/\(id)") {
                selectedTranscript = data["full_transcript"] as? String ?? "No transcript available"
            }
        }
    }
}

struct RecordingRow: View {
    let recording: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Image(systemName: mode == "meeting" ? "person.3" : "mic")
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
                Text(mode == "meeting" ? "Meeting" : "Voice Note")
                    .font(.system(size: 13, weight: .medium))
            }
            HStack {
                Text(dateString)
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                if let duration = recording["duration_seconds"] as? Double, duration > 0 {
                    Text("\(Int(duration / 60))m \(Int(duration) % 60)s")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                }
                Spacer()
                let status = recording["status"] as? String ?? ""
                if status == "completed" {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 10))
                        .foregroundColor(.green)
                } else if status == "failed" {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 10))
                        .foregroundColor(.red)
                }
            }
            if let text = recording["full_text"] as? String, !text.isEmpty {
                Text(text)
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 2)
    }

    private var mode: String { recording["mode"] as? String ?? "voice_note" }
    private var dateString: String {
        let raw = recording["created_at"] as? String ?? ""
        return String(raw.prefix(16)).replacingOccurrences(of: "T", with: " ")
    }
}

struct RecordingDetailView: View {
    let recording: [String: Any]
    let transcript: String
    @State private var rich: [String: Any] = [:]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                // Header
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Image(systemName: mode == "meeting" ? "person.3" : "mic")
                            .font(.system(size: 14))
                        Text(mode == "meeting" ? "Meeting Recording" : "Voice Note")
                            .font(.system(size: 22, weight: .bold))
                    }
                    HStack(spacing: 12) {
                        Label(dateString, systemImage: "calendar")
                        if let duration = recording["duration_seconds"] as? Double, duration > 0 {
                            Label("\(Int(duration / 60))m \(Int(duration) % 60)s", systemImage: "clock")
                        }
                        let status = recording["status"] as? String ?? "unknown"
                        Text(status.capitalized)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(status == "completed" ? .green : .orange)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background((status == "completed" ? Color.green : .orange).opacity(0.15))
                            .cornerRadius(4)
                    }
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
                }

                Divider()

                if !rich.isEmpty {
                    meetingKnowledge
                    Divider()
                }

                // Transcript
                VStack(alignment: .leading, spacing: 8) {
                    Text("Transcript")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.secondary)
                        .textCase(.uppercase)

                    if transcript.isEmpty {
                        Text("Loading transcript...")
                            .font(.system(size: 13))
                            .foregroundColor(.secondary)
                    } else {
                        Text(transcript)
                            .font(.system(size: 13))
                            .lineSpacing(4)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(24)
        }
        .task { await loadRichDetail() }
    }

    private var meetingKnowledge: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Meeting Intelligence")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)

            if let minutes = rich["minutes"] as? [String: Any], !minutes.isEmpty {
                KeyValueCard(title: "Minutes", values: minutes)
            }
            if let draft = rich["email_draft"] as? [String: Any], !draft.isEmpty {
                KeyValueCard(title: "Follow-up Draft", values: draft)
            }
            intelligenceRows("Action Items", rich["tasks"] as? [[String: Any]] ?? [])
            intelligenceRows("Decisions", rich["decisions"] as? [[String: Any]] ?? [])
            intelligenceRows("Promises", rich["promises"] as? [[String: Any]] ?? [])
        }
    }

    @ViewBuilder
    private func intelligenceRows(_ title: String, _ rows: [[String: Any]]) -> some View {
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                ForEach(rows.indices, id: \.self) { i in
                    KeyValueCard(title: rows[i]["text"] as? String ?? rows[i]["description"] as? String ?? title, values: rows[i])
                }
            }
        }
    }

    private func loadRichDetail() async {
        guard let id = recording["id"] as? String else { return }
        rich = (try? await APIClient.shared.getRawObject("/recordings/\(id)/rich")) ?? [:]
    }

    private var mode: String { recording["mode"] as? String ?? "voice_note" }
    private var dateString: String {
        let raw = recording["created_at"] as? String ?? ""
        return String(raw.prefix(16)).replacingOccurrences(of: "T", with: " ")
    }
}
