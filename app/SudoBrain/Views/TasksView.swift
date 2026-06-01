import SwiftUI

struct TasksView: View {
    @State private var tasks: [[String: Any]] = []
    @State private var filter = "All"
    @State private var isLoading = true

    var filteredTasks: [[String: Any]] {
        switch filter {
        case "Overdue":
            return tasks.filter { isOverdue($0["due_date"] as? String) }
        default:
            return tasks
        }
    }

    var overdueTasks: [[String: Any]] { tasks.filter { isOverdue($0["due_date"] as? String) } }
    var todayTasks: [[String: Any]] { tasks.filter { isToday($0["due_date"] as? String) } }
    var upcomingTasks: [[String: Any]] { tasks.filter { !isOverdue($0["due_date"] as? String) && !isToday($0["due_date"] as? String) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Text("Tasks")
                    .font(.system(size: 22, weight: .bold))
                Spacer()
                HStack(spacing: 4) {
                    ForEach(["All", "Overdue"], id: \.self) { f in
                        Button(f) { filter = f }
                            .font(.system(size: 11))
                            .buttonStyle(.bordered)
                            .tint(filter == f ? .blue : .secondary)
                    }
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 8)

            // Stats
            HStack(spacing: 16) {
                StatPill(color: .orange, text: "\(overdueTasks.count) overdue")
                StatPill(color: .blue, text: "\(todayTasks.count) due today")
                StatPill(color: .secondary, text: "\(upcomingTasks.count) upcoming")
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 12)

            Divider()

            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if tasks.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "checkmark.seal")
                        .font(.system(size: 28))
                        .foregroundColor(.green.opacity(0.5))
                    Text("No pending tasks")
                        .font(.system(size: 13))
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        if !overdueTasks.isEmpty && filter != "Overdue" {
                            TaskGroupView(title: "Overdue", tasks: overdueTasks, onChange: loadTasks)
                        }
                        if !todayTasks.isEmpty {
                            TaskGroupView(title: "Due Today", tasks: todayTasks, onChange: loadTasks)
                        }
                        if !upcomingTasks.isEmpty && filter != "Overdue" {
                            TaskGroupView(title: "Upcoming", tasks: upcomingTasks, onChange: loadTasks)
                        }
                        if filter == "Overdue" {
                            TaskGroupView(title: "Overdue", tasks: overdueTasks, onChange: loadTasks)
                        }
                    }
                    .padding(24)
                }
            }
        }
        .task { await loadTasks() }
    }

    private func loadTasks() async {
        isLoading = true
        tasks = (try? await APIClient.shared.getRaw("/action-items")) ?? []
        isLoading = false
    }

    private func isOverdue(_ dateStr: String?) -> Bool {
        guard let dateStr = dateStr, !dateStr.isEmpty else { return false }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        guard let date = f.date(from: dateStr) else { return false }
        return date < Calendar.current.startOfDay(for: Date())
    }

    private func isToday(_ dateStr: String?) -> Bool {
        guard let dateStr = dateStr, !dateStr.isEmpty else { return false }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        guard let date = f.date(from: dateStr) else { return false }
        return Calendar.current.isDateInToday(date)
    }
}

struct TaskGroupView: View {
    let title: String
    let tasks: [[String: Any]]
    let onChange: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundColor(.secondary)
                .textCase(.uppercase)
                .padding(.bottom, 4)

            ForEach(tasks.indices, id: \.self) { i in
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
                            .foregroundColor(title == "Overdue" ? .orange : title == "Due Today" ? .blue : .secondary)
                    }
                    Button {
                        Task { await complete(t["id"] as? Int) }
                    } label: {
                        Image(systemName: "checkmark")
                    }
                    .buttonStyle(.borderless)
                    Button {
                        Task { await snooze(t["id"] as? Int) }
                    } label: {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                    .buttonStyle(.borderless)
                }
                .padding(.vertical, 5)
            }
        }
    }

    private func complete(_ id: Int?) async {
        guard let id else { return }
        _ = try? await APIClient.shared.post("/action-items/\(id)/complete", body: [:])
        await onChange()
    }

    private func snooze(_ id: Int?) async {
        guard let id else { return }
        _ = try? await APIClient.shared.post("/action-items/\(id)/snooze?days=1", body: [:])
        await onChange()
    }
}

struct StatPill: View {
    let color: Color
    let text: String
    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 5, height: 5)
            Text(text).font(.system(size: 11)).foregroundColor(.secondary)
        }
    }
}
