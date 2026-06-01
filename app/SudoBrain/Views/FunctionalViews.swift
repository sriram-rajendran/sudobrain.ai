import SwiftUI
import UniformTypeIdentifiers

struct SearchView: View {
    @State private var query = ""
    @State private var mode = "Smart"
    @State private var results: [[String: Any]] = []
    @State private var objectResult: [String: Any] = [:]
    @State private var isLoading = false
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Search", systemImage: "magnifyingglass") {
                Picker("", selection: $mode) {
                    Text("Smart").tag("Smart")
                    Text("Full Text").tag("Full Text")
                    Text("Semantic").tag("Semantic")
                }
                .pickerStyle(.segmented)
                .frame(width: 260)
            }

            HStack(spacing: 8) {
                TextField("Search transcripts, decisions, tasks, people, and projects", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { runSearch() }
                Button {
                    runSearch()
                } label: {
                    Image(systemName: "arrow.right")
                }
                .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isLoading)
            }
            .padding(16)

            Divider()

            if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !message.isEmpty {
                emptyState(message, icon: "magnifyingglass")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if mode == "Smart" && !objectResult.isEmpty {
                            SmartSearchResultView(result: objectResult)
                        }
                        ForEach(results.indices, id: \.self) { i in
                            KeyValueCard(title: resultTitle(results[i]), values: results[i])
                        }
                    }
                    .padding(16)
                }
            }
        }
    }

    private func runSearch() {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isLoading = true
        message = ""
        results = []
        objectResult = [:]

        Task { @MainActor in
            do {
                let encoded = trimmed.urlEncoded
                if mode == "Smart" {
                    objectResult = try await APIClient.shared.getRawObject("/search/smart?query=\(encoded)&top_k=20")
                } else if mode == "Semantic" {
                    results = try await APIClient.shared.getRaw("/semantic-search?query=\(encoded)&limit=20")
                } else {
                    results = try await APIClient.shared.getRaw("/search?query=\(encoded)&limit=20")
                }
                if results.isEmpty && objectResult.isEmpty {
                    message = "No matching knowledge found"
                }
            } catch {
                message = error.localizedDescription
            }
            isLoading = false
        }
    }
}

struct DocumentsView: View {
    @State private var isImporterPresented = false
    @State private var result: [String: Any] = [:]
    @State private var isUploading = false
    @State private var message = "Upload a PDF, DOCX, TXT, or Markdown file to extract actions, decisions, promises, and graph relationships."

    var body: some View {
        VStack(spacing: 0) {
            header("Documents", systemImage: "doc.text") {
                Button {
                    isImporterPresented = true
                } label: {
                    Label("Upload", systemImage: "square.and.arrow.up")
                }
                .disabled(isUploading)
            }

            if isUploading {
                ProgressView("Ingesting document…").frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if result.isEmpty {
                emptyState(message, icon: "doc.badge.plus")
            } else {
                ScrollView {
                    KeyValueCard(title: result["filename"] as? String ?? "Document ingested", values: result)
                        .padding(16)
                }
            }
        }
        .fileImporter(
            isPresented: $isImporterPresented,
            allowedContentTypes: [.pdf, .plainText, .text, UTType(filenameExtension: "md") ?? .data, UTType(filenameExtension: "docx") ?? .data],
            allowsMultipleSelection: false
        ) { response in
            guard case .success(let urls) = response, let url = urls.first else { return }
            upload(url)
        }
    }

    private func upload(_ url: URL) {
        isUploading = true
        result = [:]
        message = ""
        Task { @MainActor in
            let didAccess = url.startAccessingSecurityScopedResource()
            defer {
                if didAccess { url.stopAccessingSecurityScopedResource() }
                isUploading = false
            }
            do {
                result = try await APIClient.shared.uploadFile("/ingest", fileURL: url)
            } catch {
                message = error.localizedDescription
            }
        }
    }
}

struct SourceSyncView: View {
    @State private var status: [String: Any] = [:]
    @State private var audit: [String: Any] = [:]
    @State private var isRunning = false
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Source Sync", systemImage: "arrow.triangle.2.circlepath") {
                Button { Task { await runSync() } } label: {
                    Label(isRunning ? "Running…" : "Run", systemImage: "play")
                }
                .disabled(isRunning)
                Button { Task { await load() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if !message.isEmpty { Text(message).font(.caption).foregroundColor(.secondary) }
                    KeyValueCard(title: "Status", values: status)
                    KeyValueCard(title: "Audit", values: audit)
                }
                .padding(16)
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/sync/status")) ?? [:]
        audit = (try? await APIClient.shared.getRawObject("/sync/audit")) ?? [:]
    }

    private func runSync() async {
        isRunning = true
        message = "Syncing enabled read-only sources…"
        let response = (try? await APIClient.shared.post("/sync/run", body: [:], timeout: 600)) ?? [:]
        message = response["status"] as? String ?? "Sync finished"
        await load()
        isRunning = false
    }
}

struct GmailView: View {
    @State private var status: [String: Any] = [:]
    @State private var pending: [[String: Any]] = []
    @State private var query = ""
    @State private var isSyncing = false
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Gmail", systemImage: "envelope") {
                Button { Task { await sync() } } label: {
                    Label(isSyncing ? "Syncing…" : "Sync", systemImage: "arrow.clockwise")
                }
                .disabled(isSyncing)
            }
            HStack {
                TextField("Search Gmail", text: $query)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await search() } }
                Button { Task { await search() } } label: { Image(systemName: "magnifyingglass") }
            }
            .padding(16)
            Divider()
            List {
                Section("Status") { KeyValueRows(values: status) }
                Section("Messages") {
                    ForEach(pending.indices, id: \.self) { i in
                        KeyValueCard(title: pending[i]["subject"] as? String ?? "Email", values: pending[i])
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/gmail/status")) ?? [:]
        pending = (try? await APIClient.shared.getRaw("/gmail/pending?max_results=20")) ?? []
    }

    private func sync() async {
        isSyncing = true
        _ = try? await APIClient.shared.post("/gmail/sync?days=30&max_results=30", body: [:], timeout: 600)
        await load()
        isSyncing = false
    }

    private func search() async {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { await load(); return }
        pending = (try? await APIClient.shared.getRaw("/gmail/search?q=\(q.urlEncoded)&max_results=30")) ?? []
    }
}

struct CalendarView: View {
    @State private var status: [String: Any] = [:]
    @State private var today: [[String: Any]] = []
    @State private var upcoming: [[String: Any]] = []
    @State private var next: [String: Any] = [:]

    var body: some View {
        VStack(spacing: 0) {
            header("Calendar", systemImage: "calendar") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            List {
                Section("Status") { KeyValueRows(values: status) }
                if !next.isEmpty {
                    Section("Next Meeting") { KeyValueCard(title: next["title"] as? String ?? "Next meeting", values: next) }
                }
                Section("Today") {
                    ForEach(today.indices, id: \.self) { i in
                        KeyValueCard(title: today[i]["title"] as? String ?? "Event", values: today[i])
                    }
                }
                Section("Upcoming") {
                    ForEach(upcoming.indices, id: \.self) { i in
                        KeyValueCard(title: upcoming[i]["title"] as? String ?? "Event", values: upcoming[i])
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/calendar/status")) ?? [:]
        today = (try? await APIClient.shared.getRaw("/calendar/today")) ?? []
        upcoming = (try? await APIClient.shared.getRaw("/calendar/upcoming?days=7")) ?? []
        next = (try? await APIClient.shared.getRawObject("/calendar/next-meeting")) ?? [:]
    }
}

struct LinearView: View {
    @State private var status: [String: Any] = [:]
    @State private var issues: [[String: Any]] = []
    @State private var projects: [[String: Any]] = []
    @State private var isSyncing = false

    var body: some View {
        VStack(spacing: 0) {
            header("Linear", systemImage: "list.bullet.rectangle") {
                Button { Task { await sync() } } label: {
                    Label(isSyncing ? "Syncing…" : "Sync", systemImage: "arrow.clockwise")
                }
                .disabled(isSyncing)
            }
            List {
                Section("Status") { KeyValueRows(values: status) }
                Section("Projects") {
                    ForEach(projects.indices, id: \.self) { i in
                        KeyValueCard(title: projects[i]["name"] as? String ?? "Project", values: projects[i])
                    }
                }
                Section("Issues") {
                    ForEach(issues.indices, id: \.self) { i in
                        KeyValueCard(title: issues[i]["title"] as? String ?? "Issue", values: issues[i])
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/linear/status")) ?? [:]
        projects = (try? await APIClient.shared.getRaw("/linear/projects")) ?? []
        issues = (try? await APIClient.shared.getRaw("/linear/issues?limit=50")) ?? []
    }

    private func sync() async {
        isSyncing = true
        _ = try? await APIClient.shared.post("/linear/sync?days=30", body: [:], timeout: 600)
        await load()
        isSyncing = false
    }
}

struct WorkflowsView: View {
    @State private var rules: [[String: Any]] = []
    @State private var log: [[String: Any]] = []
    @State private var name = ""
    @State private var trigger = "task_overdue"
    @State private var action = "flag_inbox"
    @State private var isRunning = false
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Workflows", systemImage: "point.3.connected.trianglepath.dotted") {
                Button { Task { await createDefaults() } } label: { Label("Defaults", systemImage: "wand.and.stars") }
                Button { Task { await evaluate() } } label: { Label(isRunning ? "Running…" : "Evaluate", systemImage: "play") }
                    .disabled(isRunning)
            }
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    TextField("Rule name", text: $name)
                    Picker("When", selection: $trigger) {
                        Text("Task overdue").tag("task_overdue")
                        Text("Promise due soon").tag("promise_due_soon")
                        Text("No interaction").tag("no_interaction")
                        Text("Unassigned task").tag("unassigned_task")
                    }
                    Picker("Action", selection: $action) {
                        Text("Flag inbox").tag("flag_inbox")
                        Text("Notify").tag("notify")
                        Text("Create reminder").tag("create_reminder")
                    }
                    Button { Task { await createRule() } } label: { Image(systemName: "plus") }
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                if !message.isEmpty { Text(message).font(.caption).foregroundColor(.secondary) }
            }
            .padding(16)
            Divider()
            List {
                Section("Rules") {
                    ForEach(rules.indices, id: \.self) { i in
                        HStack {
                            KeyValueCard(title: rules[i]["name"] as? String ?? "Rule", values: rules[i])
                            Button(role: .destructive) {
                                Task { await deleteRule(rules[i]["id"] as? Int) }
                            } label: {
                                Image(systemName: "trash")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Log") {
                    ForEach(log.indices, id: \.self) { i in
                        KeyValueCard(title: log[i]["rule_name"] as? String ?? "Run", values: log[i])
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        rules = (try? await APIClient.shared.getRaw("/workflows")) ?? []
        log = (try? await APIClient.shared.getRaw("/workflows/log?limit=50")) ?? []
    }

    private func createRule() async {
        _ = try? await APIClient.shared.post("/workflows", body: [
            "name": name,
            "trigger_type": trigger,
            "action_type": action,
            "condition": [:],
            "action_params": [:],
        ])
        name = ""
        await load()
    }

    private func createDefaults() async {
        _ = try? await APIClient.shared.post("/workflows/defaults", body: [:])
        await load()
    }

    private func evaluate() async {
        isRunning = true
        let response = (try? await APIClient.shared.post("/workflows/evaluate", body: [:])) ?? [:]
        message = "Triggered \((response["triggered"] as? [[String: Any]])?.count ?? 0) workflow action(s)"
        await load()
        isRunning = false
    }

    private func deleteRule(_ id: Int?) async {
        guard let id else { return }
        _ = try? await APIClient.shared.delete("/workflows/\(id)")
        await load()
    }
}

struct ReportsView: View {
    @State private var weekly: [String: Any] = [:]
    @State private var monthly: [String: Any] = [:]

    var body: some View {
        VStack(spacing: 0) {
            header("Reports", systemImage: "chart.line.uptrend.xyaxis") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    KeyValueCard(title: "Weekly", values: weekly)
                    KeyValueCard(title: "Monthly", values: monthly)
                }
                .padding(16)
            }
        }
        .task { await load() }
    }

    private func load() async {
        weekly = (try? await APIClient.shared.getRawObject("/reports/weekly")) ?? [:]
        monthly = (try? await APIClient.shared.getRawObject("/reports/monthly")) ?? [:]
    }
}

struct ModelsView: View {
    @State private var status: [String: Any] = [:]

    var body: some View {
        VStack(spacing: 0) {
            header("Models", systemImage: "cpu") {
                Button {
                    Task {
                        _ = try? await APIClient.shared.post("/models/refresh", body: [:])
                        await load()
                    }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
            ScrollView { KeyValueCard(title: "Runtime Models", values: status).padding(16) }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/models/status")) ?? [:]
    }
}

struct HealthDataView: View {
    @State private var correlation: [String: Any] = [:]
    @State private var type = "sleep_hours"
    @State private var value = ""
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Health", systemImage: "heart") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    TextField("Metric", text: $type)
                    TextField("Value", text: $value)
                        .frame(width: 100)
                    Button { Task { await save() } } label: { Image(systemName: "plus") }
                }
                if !message.isEmpty { Text(message).font(.caption).foregroundColor(.secondary) }
            }
            .padding(16)
            Divider()
            ScrollView { KeyValueCard(title: "Productivity Correlation", values: correlation).padding(16) }
        }
        .task { await load() }
    }

    private func load() async {
        correlation = (try? await APIClient.shared.getRawObject("/health-correlation?days=30")) ?? [:]
    }

    private func save() async {
        guard let numeric = Double(value) else {
            message = "Value must be numeric"
            return
        }
        _ = try? await APIClient.shared.post("/health-data", body: ["data_type": type, "value": numeric])
        value = ""
        message = "Saved"
        await load()
    }
}

struct SmartSearchResultView: View {
    let result: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let answer = result["answer"] as? String {
                Text(answer)
                    .font(.system(size: 14))
                    .lineSpacing(3)
            }
            KeyValueRows(values: result)
        }
        .padding(12)
        .background(Color.secondary.opacity(0.08))
        .cornerRadius(8)
    }
}

struct KeyValueCard: View {
    let title: String
    let values: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .lineLimit(2)
            KeyValueRows(values: values)
        }
        .padding(12)
        .background(Color.secondary.opacity(0.08))
        .cornerRadius(8)
    }
}

struct KeyValueRows: View {
    let values: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(displayPairs(values), id: \.0) { key, value in
                HStack(alignment: .top, spacing: 8) {
                    Text(key.replacingOccurrences(of: "_", with: " "))
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(.secondary)
                        .frame(width: 120, alignment: .leading)
                    Text(value)
                        .font(.system(size: 11))
                        .foregroundColor(.primary)
                        .lineLimit(4)
                    Spacer(minLength: 0)
                }
            }
        }
    }

    private func displayPairs(_ values: [String: Any]) -> [(String, String)] {
        values.keys.sorted().compactMap { key in
            guard key != "knowledge" else { return nil }
            return (key, compactDescription(values[key]))
        }
    }
}

@ViewBuilder
private func header<Trailing: View>(_ title: String, systemImage: String, @ViewBuilder trailing: () -> Trailing) -> some View {
    HStack {
        Label(title, systemImage: systemImage)
            .font(.system(size: 22, weight: .bold))
        Spacer()
        trailing()
    }
    .padding(.horizontal, 24)
    .padding(.top, 20)
    .padding(.bottom, 12)
    Divider()
}

private func emptyState(_ text: String, icon: String) -> some View {
    VStack(spacing: 8) {
        Image(systemName: icon)
            .font(.system(size: 30))
            .foregroundColor(.secondary.opacity(0.45))
        Text(text)
            .font(.system(size: 13))
            .foregroundColor(.secondary)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 520)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .padding(24)
}

private func resultTitle(_ row: [String: Any]) -> String {
    for key in ["title", "subject", "text", "source", "type", "id"] {
        if let value = row[key] as? String, !value.isEmpty {
            return value
        }
    }
    return "Result"
}

private func compactDescription(_ value: Any?) -> String {
    guard let value else { return "" }
    if let str = value as? String { return str }
    if let int = value as? Int { return "\(int)" }
    if let double = value as? Double { return String(format: "%.2f", double) }
    if let bool = value as? Bool { return bool ? "yes" : "no" }
    if let array = value as? [Any] { return "\(array.count) item(s)" }
    if let dict = value as? [String: Any] { return "\(dict.count) field(s)" }
    return String(describing: value)
}

private extension String {
    var urlEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? self
    }
}
