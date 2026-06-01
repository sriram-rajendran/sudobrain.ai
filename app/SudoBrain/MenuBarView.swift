import SwiftUI

struct MenuBarView: View {
    @ObservedObject var recorder: AudioRecorder

    var body: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                Image("SudoBrainLogo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 22, height: 22)
                    .cornerRadius(5)
                Text("SudoBrain")
                    .font(.system(size: 14, weight: .semibold))
                Spacer()
                statusBadge
            }

            Divider()

            // Mode Selector
            HStack(spacing: 6) {
                ModeButton(
                    title: "Voice Note",
                    icon: "mic.fill",
                    isSelected: recorder.currentMode == .voiceNote,
                    action: { recorder.currentMode = .voiceNote }
                )
                ModeButton(
                    title: "Meeting",
                    icon: "person.3.fill",
                    isSelected: recorder.currentMode == .meeting,
                    action: { recorder.currentMode = .meeting }
                )
            }

            // Recording State
            if recorder.isRecording {
                VStack(spacing: 6) {
                    HStack {
                        Text(formatDuration(recorder.recordingDuration))
                            .font(.system(.title2, design: .monospaced))
                            .foregroundColor(.red)
                        Spacer()
                        Circle()
                            .fill(Color.red)
                            .frame(width: 8, height: 8)
                            .opacity(recorder.recordingDuration.truncatingRemainder(dividingBy: 1.0) < 0.5 ? 1 : 0.3)
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 2)
                                .fill(Color.secondary.opacity(0.2))
                            RoundedRectangle(cornerRadius: 2)
                                .fill(levelColor(recorder.audioLevel))
                                .frame(width: geo.size.width * CGFloat(recorder.audioLevel))
                                .animation(.easeOut(duration: 0.1), value: recorder.audioLevel)
                        }
                    }
                    .frame(height: 4)
                }
            }

            // Record / Stop Button
            Button(action: {
                if recorder.isRecording {
                    recorder.stopRecording()
                } else {
                    recorder.startRecording()
                }
            }) {
                HStack(spacing: 6) {
                    Image(systemName: recorder.isRecording ? "stop.circle.fill" : "record.circle")
                        .font(.system(size: 14))
                    Text(recorder.isRecording ? "Stop Recording" : "Start Recording")
                        .font(.system(size: 13, weight: .medium))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 7)
            }
            .buttonStyle(.borderedProminent)
            .tint(recorder.isRecording ? .red : .blue)

            // Processing Status
            statusMessage

            // Error
            if let error = recorder.errorMessage {
                Text(error)
                    .font(.system(size: 11))
                    .foregroundColor(.red)
                    .multilineTextAlignment(.center)
            }

            // Recording History
            if !recorder.recordingHistory.isEmpty {
                Divider()

                VStack(alignment: .leading, spacing: 2) {
                    HStack {
                        Text("Recent")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)
                        Spacer()
                        Button {
                            recorder.loadRecentRecordings()
                        } label: {
                            Image(systemName: "arrow.clockwise")
                                .font(.system(size: 10))
                        }
                        .buttonStyle(.plain)
                        .foregroundColor(.secondary)
                        .help("Refresh recording history")
                    }
                    .padding(.bottom, 2)

                    ForEach(recorder.recordingHistory.prefix(5)) { entry in
                        HistoryRow(entry: entry)
                    }
                }
            }

            Divider()

            HStack {
                Button("Open Recordings") {
                    let url = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                        .appendingPathComponent("SudoBrain/recordings")
                    NSWorkspace.shared.open(url)
                }
                .font(.system(size: 11))
                .buttonStyle(.plain)
                .foregroundColor(.accentColor)

                Spacer()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
                .font(.system(size: 11))
                .buttonStyle(.plain)
                .foregroundColor(.secondary)
            }
        }
        .padding(14)
        .frame(width: 320)
        .task {
            recorder.loadRecentRecordings()
        }
    }

    // MARK: - Status

    @ViewBuilder
    private var statusBadge: some View {
        switch recorder.processingStatus {
        case .recording:
            HStack(spacing: 4) {
                Circle().fill(.red).frame(width: 6, height: 6)
                Text("REC").font(.system(size: 9, weight: .semibold)).foregroundColor(.red)
            }
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Color.red.opacity(0.15)).cornerRadius(4)
        case .processing:
            HStack(spacing: 4) {
                ProgressView().scaleEffect(0.4).frame(width: 8, height: 8)
            }
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Color.secondary.opacity(0.1)).cornerRadius(4)
        default:
            Text(recorder.currentMode == .voiceNote ? "Voice Note" : "Meeting")
                .font(.system(size: 9, weight: .medium)).foregroundColor(.secondary)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(Color.secondary.opacity(0.1)).cornerRadius(4)
        }
    }

    @ViewBuilder
    private var statusMessage: some View {
        switch recorder.processingStatus {
        case .sending:
            HStack(spacing: 6) {
                ProgressView().scaleEffect(0.6).frame(width: 14, height: 14)
                Text("Sending to backend...")
                    .font(.system(size: 11)).foregroundColor(.secondary)
            }
        case .processing:
            HStack(spacing: 6) {
                ProgressView().scaleEffect(0.6).frame(width: 14, height: 14)
                Text("Processing transcript...")
                    .font(.system(size: 11)).foregroundColor(.secondary)
            }
        case .completed(let preview):
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green).font(.system(size: 12))
                Text(preview.isEmpty ? "Transcript saved" : preview)
                    .font(.system(size: 11)).foregroundColor(.secondary).lineLimit(2)
            }
        case .failed(let msg):
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundColor(.red).font(.system(size: 12))
                Text(msg)
                    .font(.system(size: 11)).foregroundColor(.red).lineLimit(2)
            }
        default:
            EmptyView()
        }
    }

    private func formatDuration(_ duration: TimeInterval) -> String {
        let minutes = Int(duration) / 60
        let seconds = Int(duration) % 60
        let tenths = Int((duration * 10).truncatingRemainder(dividingBy: 10))
        return String(format: "%02d:%02d.%d", minutes, seconds, tenths)
    }

    private func levelColor(_ level: Float) -> Color {
        if level > 0.8 { return .red }
        if level > 0.5 { return .yellow }
        return .green
    }
}

struct ModeButton: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 10))
                Text(title).font(.system(size: 11))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 5)
        }
        .buttonStyle(.bordered)
        .tint(isSelected ? .blue : .secondary)
    }
}

struct HistoryRow: View {
    let entry: AudioRecorder.RecordingEntry

    var body: some View {
        HStack(spacing: 8) {
            statusIcon.font(.system(size: 10)).frame(width: 14)

            VStack(alignment: .leading, spacing: 1) {
                Text(entry.modeLabel)
                    .font(.system(size: 11, weight: .medium))
                if let transcript = entry.transcript, !transcript.isEmpty {
                    Text(transcript)
                        .font(.system(size: 10)).foregroundColor(.secondary).lineLimit(1)
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 1) {
                Text(timeString(entry.date))
                    .font(.system(size: 10)).foregroundColor(.secondary)
                Text(durationString(entry.duration))
                    .font(.system(size: 9)).foregroundColor(.secondary.opacity(0.6))
            }
        }
        .padding(.vertical, 3)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch entry.status {
        case .completed:
            Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
        case .failed:
            Image(systemName: "xmark.circle.fill").foregroundColor(.red)
        case .processing, .sending:
            ProgressView().scaleEffect(0.4)
        default:
            Image(systemName: "circle").foregroundColor(.secondary)
        }
    }

    private func timeString(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: date)
    }

    private func durationString(_ seconds: TimeInterval) -> String {
        let m = Int(seconds) / 60
        let s = Int(seconds) % 60
        return "\(m)m \(s)s"
    }
}
