import SwiftUI

struct GraphView: View {
    @State private var stats: [String: Any] = [:]
    @State private var bottlenecks: [[String: Any]] = []
    @State private var orphaned: [String: Any] = [:]
    @State private var selectedPerson: String? = nil
    @State private var personNetwork: [String: Any] = [:]
    @State private var selectedProject: String? = nil
    @State private var projectGraph: [String: Any] = [:]
    @State private var searchQuery = ""
    @State private var isLoading = true

    var body: some View {
        HSplitView {
            // Left: stats + navigation
            leftPanel

            // Right: detail
            rightPanel
        }
        .task { await loadData() }
    }

    // MARK: - Left Panel

    private var leftPanel: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Knowledge Graph")
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
                Button(action: { Task { await loadData() } }) {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 12))
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)

            // Stats
            if let counts = stats["counts"] as? [String: Any] {
                graphStatsGrid(counts)
            }

            Divider()

            List {
                // Bottlenecks
                if !bottlenecks.isEmpty {
                    Section("Bottlenecks") {
                        ForEach(bottlenecks.prefix(8).indices, id: \.self) { i in
                            let b = bottlenecks[i]
                            HStack {
                                Button(action: {
                                    selectedPerson = b["person"] as? String
                                    selectedProject = nil
                                    loadPersonNetwork()
                                }) {
                                    HStack {
                                        Image(systemName: "person.fill")
                                            .font(.system(size: 10))
                                            .foregroundColor(.orange)
                                        Text(b["person"] as? String ?? "?")
                                            .font(.system(size: 12))
                                        Spacer()
                                        Text("\(b["pending_count"] as? Int ?? 0) tasks")
                                            .font(.system(size: 10))
                                            .foregroundColor(.orange)
                                    }
                                }
                                .buttonStyle(.plain)
                            }
                        }
                    }
                }

                // Orphaned items
                let orphTasks = orphaned["orphaned_tasks"] as? [[String: Any]] ?? []
                if !orphTasks.isEmpty {
                    Section("Orphaned Tasks (\(orphTasks.count))") {
                        ForEach(orphTasks.prefix(5).indices, id: \.self) { i in
                            Text(orphTasks[i]["text"] as? String ?? "")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                                .lineLimit(1)
                        }
                    }
                }
            }
            .listStyle(.sidebar)
        }
        .frame(minWidth: 220, maxWidth: 260)
    }

    // MARK: - Right Panel

    @ViewBuilder
    private var rightPanel: some View {
        if let person = selectedPerson {
            personNetworkView(person)
        } else if let project = selectedProject {
            projectGraphView(project)
        } else {
            graphOverview
        }
    }

    private var graphOverview: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Knowledge Network")
                    .font(.system(size: 22, weight: .bold))
                    .padding(.top, 20)

                Text("Your knowledge is stored as a connected graph — people, projects, decisions, action items, and promises are all nodes with relationships between them.")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)

                // Graph search
                HStack {
                    Image(systemName: "magnifyingglass")
                        .font(.system(size: 12))
                        .foregroundColor(.secondary)
                    TextField("Search by person or project…", text: $searchQuery)
                        .textFieldStyle(.plain)
                        .font(.system(size: 13))
                        .onSubmit { performSearch() }
                }
                .padding(10)
                .background(Color.secondary.opacity(0.1))
                .cornerRadius(8)

                if let counts = stats["counts"] as? [String: Any] {
                    nodeBreakdown(counts)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    private func personNetworkView(_ name: String) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Button(action: { selectedPerson = nil }) {
                        Label("Back", systemImage: "chevron.left")
                            .font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                    Spacer()
                }
                .padding(.top, 16)

                Text(name)
                    .font(.system(size: 22, weight: .bold))

                let connections = personNetwork["connections"] as? [[String: Any]] ?? []
                Text("\(connections.count) connections in knowledge graph")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)

                // Group by relationship type
                let grouped = Dictionary(grouping: connections) { $0["relationship"] as? String ?? "OTHER" }

                ForEach(grouped.keys.sorted(), id: \.self) { rel in
                    let items = grouped[rel] ?? []
                    VStack(alignment: .leading, spacing: 6) {
                        Text(rel.replacingOccurrences(of: "_", with: " "))
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        ForEach(items.prefix(5).indices, id: \.self) { i in
                            let conn = items[i]
                            let props = conn["properties"] as? [String: Any] ?? [:]
                            let text = props["text"] as? String ?? props["description"] as? String ?? props["name"] as? String ?? ""
                            HStack(alignment: .top, spacing: 8) {
                                Circle()
                                    .fill(colorForRelation(rel))
                                    .frame(width: 6, height: 6)
                                    .padding(.top, 4)
                                Text(text.isEmpty ? conn["node_type"] as? String ?? "" : text)
                                    .font(.system(size: 12))
                                    .lineLimit(2)
                            }
                        }
                        if items.count > 5 {
                            Text("+ \(items.count - 5) more")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                        }
                    }
                    .padding(10)
                    .background(Color.secondary.opacity(0.06))
                    .cornerRadius(8)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    private func projectGraphView(_ name: String) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Button(action: { selectedProject = nil }) {
                        Label("Back", systemImage: "chevron.left")
                            .font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                    Spacer()
                }
                .padding(.top, 16)

                Text(name)
                    .font(.system(size: 22, weight: .bold))

                let nodes = projectGraph["nodes"] as? [[String: Any]] ?? []
                Text("\(nodes.count) connected items")
                    .font(.system(size: 13))
                    .foregroundColor(.secondary)

                ForEach(nodes.prefix(20).indices, id: \.self) { i in
                    let node = nodes[i]
                    let type = node["type"] as? String ?? ""
                    let props = node["properties"] as? [String: Any] ?? [:]
                    let text = props["text"] as? String ?? props["description"] as? String ?? ""

                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: iconForNodeType(type))
                            .font(.system(size: 12))
                            .foregroundColor(colorForNodeType(type))
                            .frame(width: 20)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(type)
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundColor(.secondary)
                            Text(text)
                                .font(.system(size: 12))
                                .lineLimit(2)
                        }
                    }
                    .padding(.vertical, 4)
                    Divider()
                }
            }
            .padding(.horizontal, 20)
        }
    }

    // MARK: - Helpers

    private func graphStatsGrid(_ counts: [String: Any]) -> some View {
        let items: [(String, Any)] = [
            ("People", counts["Person"] ?? 0),
            ("Projects", counts["Project"] ?? 0),
            ("Decisions", counts["Decision"] ?? 0),
            ("Tasks", counts["ActionItem"] ?? 0),
            ("Promises", counts["Promise"] ?? 0),
            ("Meetings", counts["Meeting"] ?? 0),
        ]
        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
            ForEach(items.indices, id: \.self) { i in
                VStack(spacing: 2) {
                    Text("\(items[i].1)")
                        .font(.system(size: 16, weight: .bold))
                    Text(items[i].0)
                        .font(.system(size: 9))
                        .foregroundColor(.secondary)
                }
                .padding(.vertical, 8)
                .frame(maxWidth: .infinity)
                .background(Color.secondary.opacity(0.08))
                .cornerRadius(8)
            }
        }
        .padding(10)
    }

    private func nodeBreakdown(_ counts: [String: Any]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Network Composition")
                .font(.system(size: 14, weight: .semibold))

            let items: [(String, String, Color)] = [
                ("Person", "person.circle.fill", .blue),
                ("Project", "folder.fill", .purple),
                ("Decision", "arrow.triangle.branch", .green),
                ("ActionItem", "checkmark.circle.fill", .orange),
                ("Promise", "hand.raised.fill", .red),
                ("Meeting", "calendar", .secondary),
            ]

            ForEach(items.indices, id: \.self) { i in
                let (key, icon, color) = items[i]
                let count = counts[key] as? Int ?? 0
                HStack(spacing: 10) {
                    Image(systemName: icon)
                        .font(.system(size: 12))
                        .foregroundColor(color)
                        .frame(width: 20)
                    Text(key == "ActionItem" ? "Action Items" : "\(key)s")
                        .font(.system(size: 13))
                    Spacer()
                    Text("\(count)")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.secondary)
                }
            }
            HStack(spacing: 10) {
                Image(systemName: "link")
                    .font(.system(size: 12))
                    .foregroundColor(.primary)
                    .frame(width: 20)
                Text("Relationships")
                    .font(.system(size: 13))
                Spacer()
                Text("\(counts["relationships"] as? Int ?? 0)")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.secondary)
            }
        }
        .padding(14)
        .background(Color.secondary.opacity(0.06))
        .cornerRadius(10)
    }

    private func performSearch() {
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        if q.isEmpty { return }
        selectedPerson = q
        selectedProject = nil
        loadPersonNetwork()
    }

    private func loadPersonNetwork() {
        guard let name = selectedPerson else { return }
        let encoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        Task { @MainActor in
            personNetwork = (try? await APIClient.shared.getRawObject("/graph/person/\(encoded)")) ?? [:]
        }
    }

    private func colorForRelation(_ rel: String) -> Color {
        switch rel {
        case "ASSIGNED_TO": return .orange
        case "MADE_DECISION": return .green
        case "PROMISED", "PROMISED_TO": return .red
        case "ATTENDED": return .blue
        default: return .secondary
        }
    }

    private func iconForNodeType(_ type: String) -> String {
        switch type {
        case "Decision": return "arrow.triangle.branch"
        case "ActionItem": return "checkmark.circle"
        case "Promise": return "hand.raised"
        case "Meeting": return "calendar"
        case "Person": return "person.circle"
        default: return "circle"
        }
    }

    private func colorForNodeType(_ type: String) -> Color {
        switch type {
        case "Decision": return .green
        case "ActionItem": return .orange
        case "Promise": return .red
        case "Meeting": return .blue
        case "Person": return .purple
        default: return .secondary
        }
    }

    @MainActor
    private func loadData() async {
        isLoading = true
        stats = (try? await APIClient.shared.getRawObject("/graph/status")) ?? [:]
        bottlenecks = (try? await APIClient.shared.getRaw("/graph/bottlenecks")) ?? []
        orphaned = (try? await APIClient.shared.getRawObject("/graph/orphaned")) ?? [:]
        isLoading = false
    }
}
