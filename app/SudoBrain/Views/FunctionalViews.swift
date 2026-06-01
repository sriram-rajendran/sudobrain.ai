import SwiftUI
import UniformTypeIdentifiers

struct OnboardingView: View {
    @State private var status: [String: Any] = [:]
    @State private var checks: [[String: Any]] = []

    var body: some View {
        VStack(spacing: 0) {
            header("Onboarding", systemImage: "checklist") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            List {
                ForEach(checks.indices, id: \.self) { i in
                    let check = checks[i]
                    HStack(spacing: 10) {
                        Image(systemName: (check["ok"] as? Bool ?? false) ? "checkmark.circle.fill" : "circle")
                            .foregroundColor((check["ok"] as? Bool ?? false) ? .green : .secondary)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(check["label"] as? String ?? "")
                                .font(.system(size: 13, weight: .medium))
                            Text(check["detail"] as? String ?? "")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/onboarding/status")) ?? [:]
        checks = status["checks"] as? [[String: Any]] ?? []
    }
}

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
    @State private var trustReport: [String: Any] = [:]
    @State private var freshness: [[String: Any]] = []
    @State private var isRunning = false
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Source Sync", systemImage: "arrow.triangle.2.circlepath") {
                Button { Task { await exportBundle() } } label: {
                    Label("Export", systemImage: "square.and.arrow.up")
                }
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
                    KeyValueCard(title: "Trust Report", values: trustReport)
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Source Freshness")
                            .font(.system(size: 13, weight: .semibold))
                        ForEach(freshness.indices, id: \.self) { i in
                            KeyValueCard(title: freshness[i]["source"] as? String ?? "Source", values: freshness[i])
                        }
                    }
                }
                .padding(16)
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/sync/status")) ?? [:]
        audit = (try? await APIClient.shared.getRawObject("/sync/audit")) ?? [:]
        trustReport = (try? await APIClient.shared.getRawObject("/knowledge/trust-report")) ?? [:]
        let fresh = (try? await APIClient.shared.getRawObject("/sources/freshness")) ?? [:]
        freshness = fresh["sources"] as? [[String: Any]] ?? []
    }

    private func runSync() async {
        isRunning = true
        message = "Syncing enabled read-only sources…"
        let response = (try? await APIClient.shared.post("/sync/run", body: [:], timeout: 600)) ?? [:]
        message = response["status"] as? String ?? "Sync finished"
        await load()
        isRunning = false
    }

    private func exportBundle() async {
        let bundle = (try? await APIClient.shared.getRawObject("/sync/export")) ?? [:]
        let count = (bundle["tables"] as? [String: Any])?.count ?? 0
        message = "Prepared export bundle with \(count) table(s)"
        status = bundle
    }
}

struct KnowledgeReviewView: View {
    @State private var items: [[String: Any]] = []
    @State private var bundle: [String: Any] = [:]
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Review Queue", systemImage: "checklist.checked") {
                Button { Task { await exportBundle() } } label: { Label("Bundle", systemImage: "shippingbox") }
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            if items.isEmpty {
                emptyState(message.isEmpty ? "No extracted knowledge waiting for review" : message, icon: "checkmark.seal")
            } else {
                List {
                    if !bundle.isEmpty {
                        Section("Approval Bundle") {
                            KeyValueCard(title: "Bundle", values: bundle)
                        }
                    }
                    ForEach(items.indices, id: \.self) { i in
                        let item = items[i]
                        VStack(alignment: .leading, spacing: 8) {
                            KeyValueCard(title: item["review_text"] as? String ?? "Review item", values: item)
                            HStack {
                                Button { Task { await review(item, action: "accept") } } label: {
                                    Label("Accept", systemImage: "checkmark")
                                }
                                Button(role: .destructive) { Task { await review(item, action: "dismiss") } } label: {
                                    Label("Dismiss", systemImage: "xmark")
                                }
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        let result = (try? await APIClient.shared.getRawObject("/review/queue?limit=100")) ?? [:]
        items = result["items"] as? [[String: Any]] ?? []
    }

    private func review(_ item: [String: Any], action: String) async {
        guard let kind = item["review_kind"] as? String, let id = item["id"] as? Int else { return }
        _ = try? await APIClient.shared.post("/review/\(kind)/\(id)/\(action)", body: [:])
        message = "\(action.capitalized)ed \(kind)"
        await load()
    }

    private func exportBundle() async {
        bundle = (try? await APIClient.shared.getRawObject("/review/bundle?limit=100")) ?? [:]
        message = "Prepared review approval bundle"
    }
}

struct PromisesView: View {
    @State private var promises: [[String: Any]] = []
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Promises", systemImage: "hand.raised") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            if promises.isEmpty {
                emptyState(message.isEmpty ? "No pending promises" : message, icon: "hand.thumbsup")
            } else {
                List {
                    ForEach(promises.indices, id: \.self) { i in
                        let p = promises[i]
                        VStack(alignment: .leading, spacing: 8) {
                            KeyValueCard(title: p["description"] as? String ?? "Promise", values: p)
                            HStack {
                                Button { Task { await act(p, "complete") } } label: { Label("Done", systemImage: "checkmark.circle") }
                                Button { Task { await act(p, "remind") } } label: { Label("Remind", systemImage: "bell") }
                                Button { Task { await act(p, "follow-up") } } label: { Label("Follow Up", systemImage: "arrowshape.turn.up.right") }
                                Button(role: .destructive) { Task { await act(p, "dispute") } } label: { Label("Dispute", systemImage: "exclamationmark.triangle") }
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        promises = (try? await APIClient.shared.getRaw("/promises")) ?? []
    }

    private func act(_ promise: [String: Any], _ action: String) async {
        guard let id = promise["id"] as? Int else { return }
        _ = try? await APIClient.shared.post("/promises/\(id)/\(action)", body: ["note": "Updated from macOS app"])
        message = "Promise \(action)"
        await load()
    }
}

struct CrossReferencesView: View {
    @State private var refs: [[String: Any]] = []
    @State private var recurring: [[String: Any]] = []
    @State private var resolution = "Resolved from review"

    var body: some View {
        VStack(spacing: 0) {
            header("Contradictions", systemImage: "exclamationmark.triangle") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            HStack {
                TextField("Resolution note", text: $resolution)
                    .textFieldStyle(.roundedBorder)
            }
            .padding(16)
            List {
                Section("Open Cross References") {
                    ForEach(refs.indices, id: \.self) { i in
                        let ref = refs[i]
                        HStack {
                            KeyValueCard(title: ref["description"] as? String ?? "Finding", values: ref)
                            Button { Task { await resolve(ref["id"] as? Int) } } label: {
                                Label("Resolve", systemImage: "checkmark")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Recurring Topics") {
                    ForEach(recurring.indices, id: \.self) { i in
                        KeyValueCard(title: recurring[i]["topic"] as? String ?? "Topic", values: recurring[i])
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        refs = (try? await APIClient.shared.getRaw("/cross-references")) ?? []
        recurring = (try? await APIClient.shared.getRaw("/cross-references/recurring")) ?? []
    }

    private func resolve(_ id: Int?) async {
        guard let id else { return }
        _ = try? await APIClient.shared.post("/cross-references/\(id)/resolve", body: ["resolution": resolution])
        await load()
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
    @State private var templates: [[String: Any]] = []
    @State private var approvals: [[String: Any]] = []
    @State private var outbox: [[String: Any]] = []
    @State private var trace: [[String: Any]] = []
    @State private var graph: [String: Any] = [:]
    @State private var name = ""
    @State private var trigger = "task_overdue"
    @State private var action = "flag_inbox"
    @State private var conditionJSON = "{}"
    @State private var actionJSON = "{}"
    @State private var isRunning = false
    @State private var message = ""
    @State private var preview: [String: Any] = [:]

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
                        Text("Recording processed").tag("recording_processed")
                        Text("Stale decision").tag("stale_decision")
                        Text("Project risk").tag("project_risk")
                    }
                    Picker("Action", selection: $action) {
                        Text("Flag inbox").tag("flag_inbox")
                        Text("Notify").tag("notify")
                        Text("Create reminder").tag("create_reminder")
                        Text("Webhook").tag("webhook")
                    }
                    TextField("Condition JSON", text: $conditionJSON)
                    TextField("Action JSON", text: $actionJSON)
                    Button { Task { await createRule() } } label: { Image(systemName: "plus") }
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Button { Task { await dryRunDraft() } } label: { Image(systemName: "testtube.2") }
                }
                if !message.isEmpty { Text(message).font(.caption).foregroundColor(.secondary) }
                if !preview.isEmpty { KeyValueCard(title: "Dry Run", values: preview) }
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
                            Button {
                                Task { await toggleRule(rules[i]) }
                            } label: {
                                Image(systemName: (rules[i]["enabled"] as? Bool ?? true) ? "pause.circle" : "play.circle")
                            }
                            .buttonStyle(.borderless)
                            Button {
                                Task { await dryRunRule(rules[i]["id"] as? Int) }
                            } label: {
                                Image(systemName: "testtube.2")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Templates") {
                    ForEach(templates.indices, id: \.self) { i in
                        HStack {
                            KeyValueCard(title: templates[i]["name"] as? String ?? "Template", values: templates[i])
                            Button { applyTemplate(templates[i]) } label: {
                                Image(systemName: "plus.circle")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Approvals") {
                    ForEach(approvals.indices, id: \.self) { i in
                        HStack {
                            KeyValueCard(title: approvals[i]["rule_name"] as? String ?? "Approval", values: approvals[i])
                            Button { Task { await decideApproval(approvals[i]["id"] as? Int, approve: true) } } label: {
                                Image(systemName: "checkmark.circle")
                            }
                            .buttonStyle(.borderless)
                            Button(role: .destructive) { Task { await decideApproval(approvals[i]["id"] as? Int, approve: false) } } label: {
                                Image(systemName: "xmark.circle")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Local Outbox") {
                    ForEach(outbox.indices, id: \.self) { i in
                        KeyValueCard(title: outbox[i]["action_type"] as? String ?? "Outbox", values: outbox[i])
                    }
                }
                Section("Log") {
                    ForEach(log.indices, id: \.self) { i in
                        HStack {
                            KeyValueCard(title: log[i]["rule_name"] as? String ?? "Run", values: log[i])
                            Button {
                                Task { await replayRun(log[i]["id"] as? Int) }
                            } label: {
                                Image(systemName: "arrow.clockwise.circle")
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
                Section("Trace") {
                    ForEach(trace.indices, id: \.self) { i in
                        KeyValueCard(title: trace[i]["step"] as? String ?? "Trace", values: trace[i])
                    }
                }
                Section("Visual Builder Graph") {
                    KeyValueCard(title: "Graph", values: graph)
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        rules = (try? await APIClient.shared.getRaw("/workflows")) ?? []
        log = (try? await APIClient.shared.getRaw("/workflows/log?limit=50")) ?? []
        templates = (try? await APIClient.shared.getRaw("/workflows/templates")) ?? []
        approvals = (try? await APIClient.shared.getRaw("/workflows/approvals")) ?? []
        outbox = (try? await APIClient.shared.getRaw("/workflows/outbox?limit=50")) ?? []
        trace = (try? await APIClient.shared.getRaw("/workflows/trace?limit=50")) ?? []
        graph = (try? await APIClient.shared.getRawObject("/workflows/graph")) ?? [:]
    }

    private func createRule() async {
        let condition = parseJSON(conditionJSON)
        let params = parseJSON(actionJSON)
        _ = try? await APIClient.shared.post("/workflows", body: [
            "name": name,
            "trigger_type": trigger,
            "action_type": action,
            "condition": condition,
            "action_params": params,
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

    private func toggleRule(_ rule: [String: Any]) async {
        guard let id = rule["id"] as? Int else { return }
        let enabled = !(rule["enabled"] as? Bool ?? true)
        _ = try? await APIClient.shared.post("/workflows/\(id)/toggle?enabled=\(enabled)", body: [:])
        await load()
    }

    private func dryRunDraft() async {
        preview = (try? await APIClient.shared.post("/workflows/dry-run", body: [
            "name": name.isEmpty ? "Preview" : name,
            "trigger_type": trigger,
            "action_type": action,
            "condition": parseJSON(conditionJSON),
            "action_params": parseJSON(actionJSON),
        ])) ?? [:]
    }

    private func dryRunRule(_ id: Int?) async {
        guard let id else { return }
        preview = (try? await APIClient.shared.getRawObject("/workflows/\(id)/dry-run")) ?? [:]
    }

    private func replayRun(_ id: Int?) async {
        guard let id else { return }
        preview = (try? await APIClient.shared.getRawObject("/workflows/log/\(id)/replay")) ?? [:]
    }

    private func applyTemplate(_ template: [String: Any]) {
        name = template["name"] as? String ?? ""
        trigger = template["trigger_type"] as? String ?? trigger
        action = template["action_type"] as? String ?? action
        conditionJSON = jsonString(template["condition"] ?? [:])
        actionJSON = jsonString(template["action_params"] ?? [:])
    }

    private func decideApproval(_ id: Int?, approve: Bool) async {
        guard let id else { return }
        let action = approve ? "approve" : "reject"
        _ = try? await APIClient.shared.post("/workflows/approvals/\(id)/\(action)", body: [:])
        await load()
    }

    private func jsonString(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8) else {
            return "{}"
        }
        return text
    }

    private func parseJSON(_ raw: String) -> [String: Any] {
        guard let data = raw.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return [:]
        }
        return object
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
    @State private var providerHealth: [String: Any] = [:]
    @State private var routingRules: [String: Any] = [:]
    @State private var routePreview: [String: Any] = [:]
    @State private var providerTest: [String: Any] = [:]
    @State private var providerRows: [[String: Any]] = []

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
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    KeyValueCard(title: "Runtime Models", values: status)
                    KeyValueCard(title: "Provider Health", values: providerHealth)
                    KeyValueCard(title: "Routing Rules", values: routingRules)
                    KeyValueCard(title: "Chat Route Preview", values: routePreview)
                    HStack {
                        Button {
                            Task { await testActiveProvider() }
                        } label: {
                            Label("Test Active Provider", systemImage: "bolt.heart")
                        }
                        if !providerTest.isEmpty {
                            KeyValueCard(title: "Provider Test", values: providerTest)
                        }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Provider Configuration")
                            .font(.system(size: 13, weight: .semibold))
                        ForEach(providerRows.indices, id: \.self) { i in
                            KeyValueCard(title: providerRows[i]["label"] as? String ?? "Provider", values: providerRows[i])
                        }
                    }
                }
                .padding(16)
            }
        }
        .task { await load() }
    }

    private func load() async {
        status = (try? await APIClient.shared.getRawObject("/models/status")) ?? [:]
        providerHealth = (try? await APIClient.shared.getRawObject("/models/providers/health")) ?? [:]
        routingRules = (try? await APIClient.shared.getRawObject("/models/routing-rules")) ?? [:]
        routePreview = (try? await APIClient.shared.getRawObject("/models/route?task=chat&privacy=local")) ?? [:]
        let config = status["provider_config"] as? [String: Any] ?? [:]
        let providers = config["providers"] as? [String: [String: Any]] ?? [:]
        providerRows = providers.keys.sorted().map { key in
            var row = providers[key] ?? [:]
            row["provider"] = key
            return row
        }
    }

    private func testActiveProvider() async {
        providerTest = (try? await APIClient.shared.post("/models/providers/test", body: [
            "prompt": "Reply with one short sentence confirming the provider is reachable.",
            "max_tokens": 32,
        ], timeout: 90)) ?? [:]
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

struct LocalSettingsView: View {
    @State private var rows: [(String, String, Bool)] = []
    @State private var values: [String: String] = [:]
    @State private var retention: [String: Any] = [:]
    @State private var retentionPreview: [String: Any] = [:]
    @State private var sourcePrivacy: [String: Any] = [:]
    @State private var message = ""

    var body: some View {
        VStack(spacing: 0) {
            header("Settings", systemImage: "slider.horizontal.3") {
                Button { Task { await save() } } label: { Label("Save", systemImage: "square.and.arrow.down") }
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            List {
                Section("Runtime & Privacy") {
                    ForEach(rows.indices, id: \.self) { i in
                        let row = rows[i]
                        HStack {
                            Text(row.0)
                                .font(.system(size: 11, weight: .medium))
                                .frame(width: 260, alignment: .leading)
                            if row.2 {
                                SecureField(row.1, text: Binding(
                                    get: { values[row.0] ?? row.1 },
                                    set: { values[row.0] = $0 }
                                ))
                            } else {
                                TextField(row.1, text: Binding(
                                    get: { values[row.0] ?? row.1 },
                                    set: { values[row.0] = $0 }
                                ))
                            }
                        }
                    }
                }
                Section("Retention Preview") {
                    KeyValueCard(title: "Policy", values: retention)
                    KeyValueCard(title: "Dry Run", values: retentionPreview)
                    KeyValueCard(title: "Source Privacy", values: sourcePrivacy)
                    Button {
                        Task { await loadRetention() }
                    } label: {
                        Label("Refresh Retention Preview", systemImage: "arrow.clockwise")
                    }
                }
                if !message.isEmpty {
                    Section { Text(message).font(.caption).foregroundColor(.secondary) }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        let status = (try? await APIClient.shared.getRawObject("/config/status")) ?? [:]
        let dict = status["values"] as? [String: [String: Any]] ?? [:]
        rows = dict.keys.sorted().map { key in
            let item = dict[key] ?? [:]
            return (key, item["value"] as? String ?? "", item["secret"] as? Bool ?? false)
        }
        values = Dictionary(uniqueKeysWithValues: rows.map { ($0.0, $0.1) })
        await loadRetention()
    }

    private func save() async {
        _ = try? await APIClient.shared.post("/config/save", body: ["values": values])
        message = "Saved to local SudoBrain config"
        await load()
    }

    private func loadRetention() async {
        retention = (try? await APIClient.shared.getRawObject("/privacy/retention")) ?? [:]
        retentionPreview = (try? await APIClient.shared.getRawObject("/privacy/retention/preview")) ?? [:]
        sourcePrivacy = (try? await APIClient.shared.getRawObject("/privacy/sources")) ?? [:]
    }
}

struct AdminDebugView: View {
    @State private var dashboard: [String: Any] = [:]
    @State private var observability: [String: Any] = [:]
    @State private var metrics: [String: Any] = [:]
    @State private var usage: [String: Any] = [:]
    @State private var scheduler: [String: Any] = [:]
    @State private var heartbeatResult: [String: Any] = [:]
    @State private var intelligenceResult: [String: Any] = [:]
    @State private var audit: [[String: Any]] = []
    @State private var requestLog: [String] = []

    var body: some View {
        VStack(spacing: 0) {
            header("Admin", systemImage: "gauge.with.dots.needle.67percent") {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
            }
            List {
                Section("Dashboard") {
                    KeyValueCard(title: "Local Status", values: dashboard)
                }
                Section("Observability") {
                    KeyValueCard(title: "Capabilities", values: observability)
                    KeyValueCard(title: "Request Metrics", values: metrics)
                    KeyValueCard(title: "Usage", values: usage)
                }
                Section("Scheduled Agents") {
                    KeyValueCard(title: "Scheduler", values: scheduler)
                    HStack {
                        Button {
                            Task { await triggerHeartbeat() }
                        } label: {
                            Label("Run Heartbeat", systemImage: "heart.text.square")
                        }
                        Button {
                            Task { await runIntelligence() }
                        } label: {
                            Label("Run Intelligence", systemImage: "brain")
                        }
                    }
                    if !heartbeatResult.isEmpty {
                        KeyValueCard(title: "Heartbeat Result", values: heartbeatResult)
                    }
                    if !intelligenceResult.isEmpty {
                        KeyValueCard(title: "Intelligence Result", values: intelligenceResult)
                    }
                }
                Section("Audit Log") {
                    ForEach(audit.indices, id: \.self) { i in
                        KeyValueCard(title: audit[i]["type"] as? String ?? "Event", values: audit[i])
                    }
                }
                Section("Request Log") {
                    ForEach(requestLog.indices, id: \.self) { i in
                        Text(requestLog[i])
                            .font(.system(size: 10, design: .monospaced))
                            .lineLimit(3)
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        dashboard = (try? await APIClient.shared.getRawObject("/admin/dashboard")) ?? [:]
        observability = (try? await APIClient.shared.getRawObject("/observability/status")) ?? [:]
        metrics = (try? await APIClient.shared.getRawObject("/observability/metrics?limit=25")) ?? [:]
        usage = (try? await APIClient.shared.getRawObject("/usage/analytics")) ?? [:]
        scheduler = (try? await APIClient.shared.getRawObject("/scheduler/status")) ?? [:]
        audit = (try? await APIClient.shared.getRaw("/admin/audit-log?limit=50")) ?? []
        let logs = (try? await APIClient.shared.getRawObject("/admin/request-log?limit=50")) ?? [:]
        requestLog = logs["lines"] as? [String] ?? []
    }

    private func triggerHeartbeat() async {
        heartbeatResult = (try? await APIClient.shared.post("/heartbeat/trigger", body: [:])) ?? [:]
        await load()
    }

    private func runIntelligence() async {
        intelligenceResult = (try? await APIClient.shared.post("/intelligence/run-now?group=all", body: [:], timeout: 180)) ?? [:]
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
