import SwiftUI

struct PlaceholderView: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "square.dashed")
                .font(.system(size: 32))
                .foregroundColor(.secondary.opacity(0.4))
            Text(title)
                .font(.system(size: 15, weight: .medium))
                .foregroundColor(.secondary)
            Text(subtitle)
                .font(.system(size: 12))
                .foregroundColor(.secondary.opacity(0.6))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct SettingsView: View {
    @State private var backendStatus = "Checking..."
    @State private var dbStats: [String: Any] = [:]
    @State private var systemStatus: [String: Any] = [:]
    @State private var isEmergencyActive = false
    @State private var systemMessage: String?

    var body: some View {
        TabView {
            Form {
                Section("Recording") {
                    LabeledContent("Default mode", value: "Voice Note")
                    LabeledContent("Meeting mode", value: "Mic + System Audio")
                    LabeledContent("Sample rate", value: "48,000 Hz")
                    LabeledContent("Format", value: "WAV 32-bit float")
                    LabeledContent("System audio", value: "ScreenCaptureKit")
                }
                Section("Transcription") {
                    LabeledContent("Engine", value: "Sarvam AI Saaras v3")
                    LabeledContent("Language", value: "Auto-detect (Tamil + English)")
                    LabeledContent("Diarization", value: "Batch API (up to 8 speakers)")
                    LabeledContent("Translation", value: "22 Indian languages")
                }
                Section("AI") {
                    LabeledContent("Engine", value: "local reasoning CLI + Ollama (local)")
                    LabeledContent("Cost", value: "Free (existing subscription)")
                    LabeledContent("Identity files", value: "SOUL.md, USER.md, RULES.md")
                }
            }
            .tabItem { Label("General", systemImage: "gear") }
            .frame(width: 500, height: 350)

            Form {
                Section("Backend Server") {
                    LabeledContent("Port", value: "8420")
                    LabeledContent("Auto-start", value: "Enabled")
                    LabeledContent("Status", value: backendStatus)
                }
                Section("Database") {
                    LabeledContent("Tables", value: "\(dbStats["tables"] as? Int ?? 0)")
                    LabeledContent("Integrity", value: dbStats["integrity"] as? String ?? "Unknown")
                }
                Section("Heartbeat") {
                    LabeledContent("Interval", value: "Every 15 minutes")
                    LabeledContent("Active hours", value: "8:00 AM - 10:00 PM")
                    LabeledContent("Morning briefing", value: "8:00 AM daily")
                }
                Section("Safety Controls") {
                    LabeledContent("Emergency stop", value: isEmergencyActive ? "Active" : "Inactive")
                    LabeledContent("Scheduler", value: schedulerRunning ? "Running" : "Paused")
                    LabeledContent("Pending approvals", value: "\(pendingActionCount)")

                    if isEmergencyActive {
                        Button {
                            Task { await resumeSystem() }
                        } label: {
                            Label("Resume SudoBrain", systemImage: "play.circle")
                        }
                    } else {
                        Button(role: .destructive) {
                            Task { await emergencyStop() }
                        } label: {
                            Label("Emergency Stop", systemImage: "stop.circle.fill")
                        }
                    }

                    if let systemMessage {
                        Text(systemMessage)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .tabItem { Label("System", systemImage: "server.rack") }
            .frame(width: 500, height: 350)

            Form {
                Section("Keyboard Shortcuts") {
                    LabeledContent("Record", value: "Cmd + R")
                    LabeledContent("Search", value: "Cmd + K")
                    LabeledContent("Today", value: "Cmd + 1")
                    LabeledContent("Chat", value: "Cmd + 2")
                    LabeledContent("Inbox", value: "Cmd + 3")
                    LabeledContent("Meetings", value: "Cmd + 4")
                    LabeledContent("People", value: "Cmd + 5")
                    LabeledContent("Decisions", value: "Cmd + 6")
                    LabeledContent("Tasks", value: "Cmd + 7")
                }
            }
            .tabItem { Label("Shortcuts", systemImage: "keyboard") }
            .frame(width: 500, height: 350)

            Form {
                Section("Data") {
                    LabeledContent("Database", value: "Configured local data directory")
                    LabeledContent("Recordings", value: "~/Documents/SudoBrain/recordings/")
                    LabeledContent("Workspace", value: "Configured local workspace")
                    LabeledContent("Backups", value: "Configured local backups")
                }
                Section("Privacy") {
                    LabeledContent("All data", value: "Local only")
                    LabeledContent("Cloud sync", value: "None")
                    LabeledContent("External APIs", value: "Sarvam AI (audio only)")
                }
            }
            .tabItem { Label("Privacy", systemImage: "lock.shield") }
            .frame(width: 500, height: 350)
        }
        .padding(20)
        .task {
            await refreshSystem()
        }
    }

    private var schedulerRunning: Bool {
        (systemStatus["scheduler"] as? [String: Any])?["running"] as? Bool ?? false
    }

    private var pendingActionCount: Int {
        ((systemStatus["guardrails"] as? [String: Any])?["pending_actions"] as? Int) ?? 0
    }

    private func refreshSystem() async {
        do {
            let _ = try await APIClient.shared.getRawObject("/health")
            backendStatus = "Running (port 8420)"
        } catch {
            backendStatus = "Not running"
        }

        if let statsData = try? await APIClient.shared.getRawObject("/stats") {
            dbStats = statsData["database"] as? [String: Any] ?? [:]
        }

        if let status = try? await APIClient.shared.getRawObject("/system/status") {
            systemStatus = status
            let emergency = status["emergency_stop"] as? [String: Any]
            isEmergencyActive = emergency?["active"] as? Bool ?? false
        }
    }

    private func emergencyStop() async {
        do {
            systemStatus = try await APIClient.shared.post(
                "/system/emergency-stop",
                body: ["reason": "Activated from macOS Settings"],
                timeout: 30
            )
            let emergency = systemStatus["emergency_stop"] as? [String: Any]
            isEmergencyActive = emergency?["active"] as? Bool ?? false
            systemMessage = "Proactive jobs paused and pending hard actions rejected."
        } catch {
            systemMessage = "Emergency stop failed: \(error.localizedDescription)"
        }
    }

    private func resumeSystem() async {
        do {
            systemStatus = try await APIClient.shared.post(
                "/system/resume",
                body: ["reason": "Resumed from macOS Settings"],
                timeout: 30
            )
            let emergency = systemStatus["emergency_stop"] as? [String: Any]
            isEmergencyActive = emergency?["active"] as? Bool ?? false
            systemMessage = "SudoBrain proactive jobs resumed."
        } catch {
            systemMessage = "Resume failed: \(error.localizedDescription)"
        }
    }
}
