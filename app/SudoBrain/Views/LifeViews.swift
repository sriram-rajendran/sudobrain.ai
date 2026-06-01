import SwiftUI

// MARK: - Habits View

struct HabitsView: View {
    @State private var habits: [[String: Any]] = []
    @State private var isLoading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Habits")
                    .font(.system(size: 22, weight: .bold))
                Spacer()
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 12)

            Divider()

            if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if habits.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "chart.bar")
                        .font(.system(size: 28))
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("No habits tracked yet")
                        .font(.system(size: 13))
                        .foregroundColor(.secondary)
                    Text("Say \"I worked out today\" in chat to start tracking")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary.opacity(0.6))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(habits.indices, id: \.self) { i in
                            let h = habits[i]
                            HStack(spacing: 12) {
                                Image(systemName: "chart.bar")
                                    .font(.system(size: 14))
                                    .foregroundColor(.blue)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(h["name"] as? String ?? "")
                                        .font(.system(size: 14, weight: .medium))
                                    Text("Streak: \(h["streak"] as? Int ?? 0) days")
                                        .font(.system(size: 11))
                                        .foregroundColor(.secondary)
                                }
                                Spacer()
                                Text("\(h["total_logged"] as? Int ?? 0) total")
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                            }
                            .padding(12)
                            .background(.quaternary.opacity(0.3))
                            .cornerRadius(8)
                        }
                    }
                    .padding(24)
                }
            }
        }
        .task {
            isLoading = true
            habits = (try? await APIClient.shared.getRaw("/habits")) ?? []
            isLoading = false
        }
    }
}

// MARK: - Expenses View

struct ExpensesView: View {
    @State private var expenses: [[String: Any]] = []
    @State private var summary: [String: Any] = [:]
    @State private var isLoading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Expenses")
                    .font(.system(size: 22, weight: .bold))
                Spacer()
                if let total = summary["total"] as? Double, total > 0 {
                    Text("Total: \(Int(total))")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(.orange)
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 12)

            Divider()

            if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if expenses.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "indianrupeesign.circle")
                        .font(.system(size: 28))
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("No expenses logged yet")
                        .font(.system(size: 13))
                        .foregroundColor(.secondary)
                    Text("Say \"Spent 2000 on groceries\" in chat")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary.opacity(0.6))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(expenses.indices, id: \.self) { i in
                            let e = expenses[i]
                            HStack(spacing: 10) {
                                Text(e["category"] as? String ?? "misc")
                                    .font(.system(size: 10))
                                    .foregroundColor(.secondary)
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 1)
                                    .background(.quaternary)
                                    .cornerRadius(3)
                                Text(e["description"] as? String ?? "")
                                    .font(.system(size: 13))
                                Spacer()
                                Text("\(Int(e["amount"] as? Double ?? 0))")
                                    .font(.system(size: 13, weight: .semibold))
                                Text(e["date"] as? String ?? "")
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                            }
                            .padding(.vertical, 4)
                        }
                    }
                    .padding(24)
                }
            }
        }
        .task {
            isLoading = true
            async let e = APIClient.shared.getRaw("/expenses")
            async let s = APIClient.shared.getRawObject("/expenses/summary")
            expenses = (try? await e) ?? []
            summary = (try? await s) ?? [:]
            isLoading = false
        }
    }
}

// MARK: - Ideas View

struct IdeasView: View {
    @State private var ideas: [[String: Any]] = []
    @State private var isLoading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Ideas")
                    .font(.system(size: 22, weight: .bold))
                Spacer()
                Text("\(ideas.count) parked")
                    .font(.system(size: 12))
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 12)

            Divider()

            if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if ideas.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "lightbulb")
                        .font(.system(size: 28))
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("No ideas captured yet")
                        .font(.system(size: 13))
                        .foregroundColor(.secondary)
                    Text("Say \"idea: gamify the onboarding\" in chat")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary.opacity(0.6))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(ideas.indices, id: \.self) { i in
                            let idea = ideas[i]
                            VStack(alignment: .leading, spacing: 4) {
                                Text(idea["text"] as? String ?? "")
                                    .font(.system(size: 14))
                                HStack {
                                    if let cat = idea["category"] as? String, !cat.isEmpty {
                                        Text(cat)
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                            .padding(.horizontal, 5)
                                            .padding(.vertical, 1)
                                            .background(.quaternary)
                                            .cornerRadius(3)
                                    }
                                    Text(idea["status"] as? String ?? "parked")
                                        .font(.system(size: 10))
                                        .foregroundColor(.orange)
                                    Spacer()
                                    if let date = idea["created_at"] as? String {
                                        Text(String(date.prefix(10)))
                                            .font(.system(size: 10))
                                            .foregroundColor(.secondary)
                                    }
                                }
                            }
                            .padding(10)
                            .background(.quaternary.opacity(0.3))
                            .cornerRadius(8)
                        }
                    }
                    .padding(24)
                }
            }
        }
        .task {
            isLoading = true
            ideas = (try? await APIClient.shared.getRaw("/ideas")) ?? []
            isLoading = false
        }
    }
}
