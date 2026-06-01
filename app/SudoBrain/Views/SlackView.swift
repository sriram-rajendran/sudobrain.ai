import SwiftUI

struct SlackView: View {
    @State private var channels: [[String: Any]] = []
    @State private var pendingItems: [String: Any] = [:]
    @State private var engagementStats: [String: Any] = [:]
    @State private var selectedChannel: [String: Any]? = nil
    @State private var channelMessages: [[String: Any]] = []
    @State private var isLoading = true
    @State private var isSyncing = false
    @State private var syncStatus = ""

    var body: some View {
        HSplitView {
            // Left: Channel list + stats
            VStack(spacing: 0) {
                // Header
                HStack {
                    Text("Slack")
                        .font(.system(size: 18, weight: .semibold))
                    Spacer()
                    Button(action: syncAll) {
                        Label(isSyncing ? "Syncing…" : "Sync", systemImage: "arrow.clockwise")
                            .font(.system(size: 11))
                    }
                    .buttonStyle(.bordered)
                    .disabled(isSyncing)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)

                // Pending alerts
                if !pendingItems.isEmpty {
                    pendingSection
                }

                Divider()

                // Channel list
                List(selection: Binding(
                    get: { selectedChannel?["id"] as? String },
                    set: { id in
                        selectedChannel = channels.first { $0["id"] as? String == id }
                        if let ch = selectedChannel {
                            loadMessages(ch)
                        }
                    }
                )) {
                    if !channels.isEmpty {
                        Section("Channels (\(channels.count))") {
                            ForEach(channels.indices, id: \.self) { i in
                                let ch = channels[i]
                                ChannelRow(channel: ch)
                                    .tag(ch["id"] as? String ?? "")
                            }
                        }
                    }
                }
                .listStyle(.sidebar)

                if !syncStatus.isEmpty {
                    Text(syncStatus)
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                        .padding(.horizontal, 12)
                        .padding(.bottom, 6)
                }
            }
            .frame(minWidth: 220, maxWidth: 260)

            // Right: Channel detail / messages
            if let ch = selectedChannel {
                channelDetail(ch)
            } else {
                slackOverview
            }
        }
        .task { await loadData() }
    }

    // MARK: - Subviews

    private var pendingSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("NEEDS ATTENTION")
                .font(.system(size: 9, weight: .semibold))
                .foregroundColor(.secondary)
                .padding(.horizontal, 16)
                .padding(.top, 8)

            let questions = pendingItems["unanswered_questions"] as? [[String: Any]] ?? []
            let mentions = pendingItems["unanswered_mentions"] as? [[String: Any]] ?? []
            let stale = pendingItems["stale_threads"] as? [[String: Any]] ?? []

            HStack(spacing: 8) {
                PendingPill(count: questions.count, label: "Questions", color: .orange)
                PendingPill(count: mentions.count, label: "Mentions", color: .blue)
                PendingPill(count: stale.count, label: "Stale", color: .red)
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
        .background(Color.orange.opacity(0.05))
    }

    private var slackOverview: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Slack Overview")
                    .font(.system(size: 22, weight: .bold))
                    .padding(.top, 20)

                // Engagement stats
                let senders = engagementStats["top_senders"] as? [[String: Any]] ?? []
                let totals = engagementStats["totals"] as? [String: Any] ?? [:]

                if !totals.isEmpty {
                    SlackStatCard(
                        total: totals["total_messages"] as? Int ?? 0,
                        users: totals["total_users"] as? Int ?? 0,
                        channels: totals["total_channels"] as? Int ?? 0
                    )
                }

                if !senders.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Most Active")
                            .font(.system(size: 13, weight: .semibold))

                        ForEach(senders.prefix(5).indices, id: \.self) { i in
                            let s = senders[i]
                            HStack {
                                Text(s["user_name"] as? String ?? "Unknown")
                                    .font(.system(size: 13))
                                Spacer()
                                Text("\(s["message_count"] as? Int ?? 0) messages")
                                    .font(.system(size: 12))
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                    .padding(12)
                    .background(Color.secondary.opacity(0.08))
                    .cornerRadius(10)
                }

                // Pending items detail
                let questions = pendingItems["unanswered_questions"] as? [[String: Any]] ?? []
                if !questions.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Unanswered Questions")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.orange)

                        ForEach(questions.prefix(5).indices, id: \.self) { i in
                            let q = questions[i]
                            VStack(alignment: .leading, spacing: 2) {
                                Text(q["text"] as? String ?? "")
                                    .font(.system(size: 12))
                                    .lineLimit(2)
                                Text("— \(q["user_name"] as? String ?? "?") in #\(q["channel_name"] as? String ?? "?")")
                                    .font(.system(size: 10))
                                    .foregroundColor(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                    .padding(12)
                    .background(Color.orange.opacity(0.08))
                    .cornerRadius(10)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    @ViewBuilder
    private func channelDetail(_ ch: [String: Any]) -> some View {
        VStack(spacing: 0) {
            // Channel header
            HStack {
                Text("#\(ch["name"] as? String ?? "")")
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
                Text("\(channelMessages.count) messages")
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            Divider()

            // Messages
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(channelMessages.prefix(50).indices, id: \.self) { i in
                        let msg = channelMessages[i]
                        SlackMessageRow(message: msg)
                    }
                }
                .padding(16)
            }
        }
    }

    // MARK: - Data Loading

    @MainActor
    private func loadData() async {
        isLoading = true
        do {
            channels = (try? await APIClient.shared.getRaw("/slack/channels")) ?? []
            let pending = (try? await APIClient.shared.getRawObject("/slack/pending")) ?? [:]
            pendingItems = pending
            let engagement = (try? await APIClient.shared.getRawObject("/slack/engagement")) ?? [:]
            engagementStats = engagement
        }
        isLoading = false
    }

    private func loadMessages(_ ch: [String: Any]) {
        guard let cid = ch["id"] as? String else { return }
        Task { @MainActor in
            channelMessages = (try? await APIClient.shared.getRaw("/slack/messages/\(cid)?limit=50")) ?? []
        }
    }

    private func syncAll() {
        isSyncing = true
        syncStatus = "Syncing channels…"
        Task { @MainActor in
            _ = try? await APIClient.shared.post("/slack/sync/channels", body: [:])
            syncStatus = "Fetching messages…"
            _ = try? await APIClient.shared.post("/slack/sync", body: ["messages_per_channel": 30])
            syncStatus = "Done"
            await loadData()
            isSyncing = false
        }
    }
}

struct ChannelRow: View {
    let channel: [String: Any]

    var body: some View {
        HStack(spacing: 8) {
            Text("#")
                .font(.system(size: 12))
                .foregroundColor(.secondary)
            Text(channel["name"] as? String ?? "unknown")
                .font(.system(size: 13))
            Spacer()
            if let count = channel["total_messages"] as? Int, count > 0 {
                Text("\(count)")
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
            }
        }
    }
}

struct PendingPill: View {
    let count: Int
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Text("\(count)")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(color)
            Text(label)
                .font(.system(size: 11))
                .foregroundColor(.secondary)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.1))
        .cornerRadius(6)
    }
}

struct SlackStatCard: View {
    let total: Int
    let users: Int
    let channels: Int

    var body: some View {
        HStack(spacing: 0) {
            StatPill2(value: total, label: "Messages")
            Divider().frame(height: 30)
            StatPill2(value: users, label: "People")
            Divider().frame(height: 30)
            StatPill2(value: channels, label: "Channels")
        }
        .padding(12)
        .background(Color.secondary.opacity(0.08))
        .cornerRadius(10)
    }
}

struct StatPill2: View {
    let value: Int
    let label: String

    var body: some View {
        VStack(spacing: 2) {
            Text("\(value)")
                .font(.system(size: 18, weight: .bold))
            Text(label)
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

struct SlackMessageRow: View {
    let message: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(message["user_name"] as? String ?? "Unknown")
                    .font(.system(size: 12, weight: .semibold))
                Spacer()
                if let replyCount = message["reply_count"] as? Int, replyCount > 0 {
                    Label("\(replyCount)", systemImage: "bubble.left")
                        .font(.system(size: 10))
                        .foregroundColor(.secondary)
                }
            }
            Text(message["text"] as? String ?? "")
                .font(.system(size: 12))
                .foregroundColor(.primary)
                .lineLimit(4)
        }
        .padding(.vertical, 4)
        Divider()
    }
}
