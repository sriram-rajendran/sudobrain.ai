import SwiftUI

struct PeopleView: View {
    @State private var people: [[String: Any]] = []
    @State private var selectedPersonId: Int?
    @State private var personDetail: [String: Any]?
    @State private var isLoading = true

    var body: some View {
        HSplitView {
            // People list
            VStack(alignment: .leading, spacing: 0) {
                Text("People")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(.secondary)
                    .textCase(.uppercase)
                    .padding(.horizontal, 12)
                    .padding(.top, 10)
                    .padding(.bottom, 6)

                if isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if people.isEmpty {
                    VStack(spacing: 8) {
                        Image(systemName: "person.3")
                            .font(.system(size: 24))
                            .foregroundColor(.secondary.opacity(0.4))
                        Text("No people yet")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                        Text("Record meetings to auto-detect people")
                            .font(.system(size: 11))
                            .foregroundColor(.secondary.opacity(0.6))
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(selection: $selectedPersonId) {
                        ForEach(people, id: \.selfKey) { person in
                            PersonRow(person: person)
                                .tag(person["id"] as? Int ?? 0)
                        }
                    }
                    .listStyle(.sidebar)
                }
            }
            .frame(minWidth: 220, maxWidth: 280)
            .onChange(of: selectedPersonId) { newValue in
                if let id = newValue { loadPersonDetail(id: id) }
            }

            // Detail
            if let detail = personDetail {
                PersonDetailView(person: detail)
            } else {
                PlaceholderView(title: "Select a person", subtitle: "Choose from the list to see their profile")
            }
        }
        .task { await loadPeople() }
    }

    private func loadPeople() async {
        isLoading = true
        do {
            people = try await APIClient.shared.getRaw("/people")
            isLoading = false
        } catch {
            isLoading = false
        }
    }

    private func loadPersonDetail(id: Int) {
        Task {
            personDetail = try? await APIClient.shared.getRawObject("/people/\(id)")
        }
    }
}

private extension Dictionary where Key == String, Value == Any {
    var selfKey: Int { self["id"] as? Int ?? 0 }
}

struct PersonRow: View {
    let person: [String: Any]

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(.quaternary)
                .frame(width: 30, height: 30)
                .overlay(
                    Text(initial)
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(.secondary)
                )
            VStack(alignment: .leading, spacing: 1) {
                Text(name)
                    .font(.system(size: 13, weight: .medium))
                if let role = person["role"] as? String, !role.isEmpty {
                    Text(role)
                        .font(.system(size: 11))
                        .foregroundColor(.secondary)
                }
            }
            Spacer()
            let tasks = person["pending_tasks"] as? Int ?? 0
            let promises = person["pending_promises_to"] as? Int ?? 0
            if tasks + promises > 0 {
                Text("\(tasks + promises)")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundColor(.white)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .background(.blue)
                    .cornerRadius(8)
            }
        }
        .padding(.vertical, 2)
    }

    private var name: String { person["name"] as? String ?? "Unknown" }
    private var initial: String { String(name.prefix(1)).uppercased() }
}

struct PersonDetailView: View {
    let person: [String: Any]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                // Header
                HStack(spacing: 14) {
                    Circle()
                        .fill(.quaternary)
                        .frame(width: 48, height: 48)
                        .overlay(
                            Text(String((person["name"] as? String ?? "?").prefix(1)).uppercased())
                                .font(.system(size: 20, weight: .semibold))
                                .foregroundColor(.secondary)
                        )
                    VStack(alignment: .leading, spacing: 2) {
                        Text(person["name"] as? String ?? "Unknown")
                            .font(.system(size: 20, weight: .bold))
                        if let role = person["role"] as? String, !role.isEmpty {
                            Text(role)
                                .font(.system(size: 13))
                                .foregroundColor(.secondary)
                        }
                    }
                }

                // Stats
                HStack(spacing: 20) {
                    StatItem(label: "Interactions", value: "\(person["total_interactions"] as? Int ?? 0)")
                    if let last = person["last_interaction"] as? String, !last.isEmpty {
                        StatItem(label: "Last spoke", value: String(last.prefix(10)))
                    }
                }
                .padding(.vertical, 8)

                Divider()

                // Promises
                if let promises = person["promises"] as? [[String: Any]], !promises.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Promises (\(promises.count))", systemImage: "handshake")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        ForEach(promises.indices, id: \.self) { i in
                            let p = promises[i]
                            HStack(spacing: 8) {
                                Circle()
                                    .fill((p["status"] as? String) == "pending" ? .orange : .green)
                                    .frame(width: 5, height: 5)
                                Text("\(p["promised_by_name"] as? String ?? "") -> \(p["promised_to_name"] as? String ?? ""): \(p["description"] as? String ?? "")")
                                    .font(.system(size: 13))
                                Spacer()
                                if let due = p["due_date"] as? String {
                                    Text(due)
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }

                // Tasks
                if let tasks = person["tasks"] as? [[String: Any]], !tasks.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Assigned Tasks (\(tasks.count))", systemImage: "checkmark.circle")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.secondary)
                            .textCase(.uppercase)

                        ForEach(tasks.indices, id: \.self) { i in
                            let t = tasks[i]
                            HStack(spacing: 8) {
                                Circle()
                                    .strokeBorder(Color.secondary.opacity(0.3), lineWidth: 1.5)
                                    .frame(width: 14, height: 14)
                                Text(t["text"] as? String ?? "")
                                    .font(.system(size: 13))
                                Spacer()
                                if let due = t["due_date"] as? String {
                                    Text(due)
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                }
                            }
                            .padding(.vertical, 2)
                        }
                    }
                }
            }
            .padding(24)
        }
    }
}

struct StatItem: View {
    let label: String
    let value: String
    var body: some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.system(size: 14, weight: .semibold))
            Text(label)
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
    }
}
