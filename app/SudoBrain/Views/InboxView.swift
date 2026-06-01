import SwiftUI

struct InboxView: View {
    @State private var inbox: [String: Any] = [:]
    @State private var overview: [String: Any] = [:]
    @State private var projects: [[String: Any]] = []
    @State private var isLoading = true
    @State private var actionMessage: String?

    var items: [[String: Any]] {
        inbox["items"] as? [[String: Any]] ?? []
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Inbox")
                    .font(.system(size: 28, weight: .bold))

                if let actionMessage {
                    Text(actionMessage)
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(.quaternary.opacity(0.35))
                        .cornerRadius(8)
                }

                // Overview stats
                if !overview.isEmpty {
                    HStack(spacing: 16) {
                        OverviewStat(value: "\(overview["recordings"] as? Int ?? 0)", label: "Recordings")
                        OverviewStat(value: "\(overview["pending_tasks"] as? Int ?? 0)", label: "Pending Tasks")
                        OverviewStat(value: "\(overview["decisions"] as? Int ?? 0)", label: "Decisions")
                        OverviewStat(value: "\(overview["people"] as? Int ?? 0)", label: "People")
                        OverviewStat(value: "\(overview["learned_rules"] as? Int ?? 0)", label: "Rules Learned")
                    }
                    .padding(14)
                    .background(.quaternary.opacity(0.5))
                    .cornerRadius(10)
                }

                // Knowledge growth bars
                if !overview.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Knowledge Base")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        KnowledgeBar(label: "Recordings", value: overview["recordings"] as? Int ?? 0, max: 100, color: .blue)
                        KnowledgeBar(label: "Tasks", value: overview["action_items"] as? Int ?? 0, max: 50, color: .green)
                        KnowledgeBar(label: "Decisions", value: overview["decisions"] as? Int ?? 0, max: 20, color: .purple)
                        KnowledgeBar(label: "Embeddings", value: overview["embeddings"] as? Int ?? 0, max: 200, color: .orange)

                        if let rate = overview["promise_fulfillment_rate"] as? Double {
                            HStack {
                                Text("Promise fulfillment")
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                                Spacer()
                                Text("\(Int(rate))%")
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundColor(rate > 70 ? .green : rate > 40 ? .orange : .red)
                            }
                        }
                    }
                    .padding(14)
                    .background(.quaternary.opacity(0.5))
                    .cornerRadius(10)
                }

                // Project health
                if !projects.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Project Health")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        ForEach(projects.indices, id: \.self) { i in
                            let p = projects[i]
                            HStack {
                                Circle()
                                    .fill(healthColor(p["health"] as? String ?? ""))
                                    .frame(width: 6, height: 6)
                                Text(p["project"] as? String ?? "")
                                    .font(.system(size: 12, weight: .medium))
                                Spacer()
                                Text("\(p["completed"] as? Int ?? 0)/\(p["total_tasks"] as? Int ?? 0) done")
                                    .font(.system(size: 10))
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                    .padding(14)
                    .background(.quaternary.opacity(0.5))
                    .cornerRadius(10)
                }

                if isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 40)
                } else if items.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "checkmark.seal")
                            .font(.system(size: 28))
                            .foregroundColor(.green.opacity(0.5))
                        Text("All clear")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundColor(.secondary)
                        Text("Nothing needs your attention right now.")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary.opacity(0.6))
                    }
                    .padding(.vertical, 20)
                    .frame(maxWidth: .infinity)
                } else {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("\(items.count) items need attention")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        ForEach(items.indices, id: \.self) { i in
                            InboxItemRow(
                                item: items[i],
                                onApprove: approvePendingAction,
                                onReject: rejectPendingAction
                            )
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
        async let i = APIClient.shared.getRawObject("/inbox")
        async let o = APIClient.shared.getRawObject("/insights/overview")
        async let p = APIClient.shared.getRaw("/insights/projects")
        inbox = (try? await i) ?? [:]
        overview = (try? await o) ?? [:]
        projects = (try? await p) ?? []
        isLoading = false
    }

    private func approvePendingAction(_ id: Int) {
        Task {
            do {
                _ = try await APIClient.shared.post("/actions/\(id)/approve", timeout: 30)
                await MainActor.run { actionMessage = "Action approved." }
                await loadData()
            } catch {
                await MainActor.run { actionMessage = "Could not approve action: \(error.localizedDescription)" }
            }
        }
    }

    private func rejectPendingAction(_ id: Int) {
        Task {
            do {
                _ = try await APIClient.shared.post("/actions/\(id)/reject", timeout: 30)
                await MainActor.run { actionMessage = "Action rejected." }
                await loadData()
            } catch {
                await MainActor.run { actionMessage = "Could not reject action: \(error.localizedDescription)" }
            }
        }
    }

    private func healthColor(_ health: String) -> Color {
        switch health {
        case "healthy": return .green
        case "at_risk": return .orange
        case "stalled": return .red
        default: return .secondary
        }
    }
}

struct OverviewStat: View {
    let value: String
    let label: String
    var body: some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.system(size: 16, weight: .semibold))
            Text(label)
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
    }
}

struct KnowledgeBar: View {
    let label: String
    let value: Int
    let max: Int
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 11))
                .foregroundColor(.secondary)
                .frame(width: 80, alignment: .leading)
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.secondary.opacity(0.15))
                    RoundedRectangle(cornerRadius: 2)
                        .fill(color)
                        .frame(width: geo.size.width * CGFloat(min(Double(value) / Double(max), 1.0)))
                }
            }
            .frame(height: 6)
            Text("\(value)")
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(.secondary)
                .frame(width: 30, alignment: .trailing)
        }
    }
}

struct InboxItemRow: View {
    let item: [String: Any]
    var onApprove: ((Int) -> Void)? = nil
    var onReject: ((Int) -> Void)? = nil

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundColor(iconColor)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 13, weight: .medium))
                if let desc = item["description"] as? String, !desc.isEmpty {
                    Text(desc)
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
            if itemType == "pending_approval", let actionID {
                HStack(spacing: 6) {
                    Button {
                        onApprove?(actionID)
                    } label: {
                        Image(systemName: "checkmark")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    .buttonStyle(.borderless)
                    .help("Approve action")

                    Button {
                        onReject?(actionID)
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    .buttonStyle(.borderless)
                    .help("Reject action")
                }
            } else {
                Text(typeBadge)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(iconColor)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(iconColor.opacity(0.15))
                    .cornerRadius(4)
            }
        }
        .padding(10)
        .background(.quaternary.opacity(0.3))
        .cornerRadius(8)
    }

    private var itemType: String { item["type"] as? String ?? "" }
    private var actionID: Int? { item["id"] as? Int }

    private var icon: String {
        switch itemType {
        case "contradiction": return "exclamationmark.triangle"
        case "overdue_promise": return "handshake"
        case "pending_evaluation": return "arrow.triangle.branch"
        case "unprocessed_recording": return "waveform"
        case "pending_approval": return "lock"
        default: return "circle"
        }
    }

    private var iconColor: Color {
        switch itemType {
        case "contradiction": return .red
        case "overdue_promise": return .orange
        case "pending_evaluation": return .blue
        case "unprocessed_recording": return .purple
        case "pending_approval": return .yellow
        default: return .secondary
        }
    }

    private var title: String {
        switch itemType {
        case "contradiction": return item["description"] as? String ?? "Contradiction detected"
        case "overdue_promise": return "Promise to \(item["to"] as? String ?? "?"): \(item["description"] as? String ?? "")"
        case "pending_evaluation": return "Evaluate: \(item["text"] as? String ?? "")"
        case "unprocessed_recording": return "Unprocessed \(item["mode"] as? String ?? "recording")"
        case "pending_approval": return "Approve: \(item["description"] as? String ?? "")"
        default: return "Item"
        }
    }

    private var typeBadge: String {
        switch itemType {
        case "contradiction": return "CONFLICT"
        case "overdue_promise": return "OVERDUE"
        case "pending_evaluation": return "EVALUATE"
        case "unprocessed_recording": return "PROCESS"
        case "pending_approval": return "APPROVE"
        default: return itemType
        }
    }
}
