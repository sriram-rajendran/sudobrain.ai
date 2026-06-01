import SwiftUI

struct DecisionsView: View {
    @State private var decisions: [[String: Any]] = []
    @State private var calibration: [[String: Any]] = []
    @State private var isLoading = true
    @State private var filter = "All"

    var filteredDecisions: [[String: Any]] {
        switch filter {
        case "Pending Eval":
            return decisions.filter { ($0["status"] as? String) == "tracked" }
        case "Evaluated":
            return decisions.filter { ($0["status"] as? String) == "evaluated" }
        default:
            return decisions
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack {
                Text("Decision Journal")
                    .font(.system(size: 22, weight: .bold))
                Spacer()
                HStack(spacing: 4) {
                    ForEach(["All", "Pending Eval", "Evaluated"], id: \.self) { f in
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
                StatPill(color: .blue, text: "\(decisions.count) total")
                StatPill(color: .orange, text: "\(decisions.filter { ($0["status"] as? String) == "tracked" }.count) tracked")
                StatPill(color: .green, text: "\(decisions.filter { ($0["status"] as? String) == "evaluated" }.count) evaluated")
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 12)

            Divider()

            if isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if decisions.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.branch")
                        .font(.system(size: 28))
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("No decisions logged yet")
                        .font(.system(size: 13))
                        .foregroundColor(.secondary)
                    Text("Record meetings to auto-detect decisions")
                        .font(.system(size: 11))
                        .foregroundColor(.secondary.opacity(0.6))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(filteredDecisions.indices, id: \.self) { i in
                            DecisionRow(decision: filteredDecisions[i])
                        }
                    }
                    .padding(24)
                }
            }
        }
        .task { await loadData() }
    }

    private func loadData() async {
        isLoading = true
        decisions = (try? await APIClient.shared.getRaw("/decisions")) ?? []
        calibration = (try? await APIClient.shared.getRaw("/decisions/calibration")) ?? []
        isLoading = false
    }
}

struct DecisionRow: View {
    let decision: [String: Any]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Decision text
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "arrow.triangle.branch")
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                    .frame(width: 16, alignment: .center)
                    .padding(.top, 2)

                VStack(alignment: .leading, spacing: 4) {
                    Text(decision["text"] as? String ?? "")
                        .font(.system(size: 14, weight: .medium))

                    HStack(spacing: 8) {
                        // Confidence badge
                        if let conf = decision["confidence"] as? Int {
                            HStack(spacing: 3) {
                                Text("\(conf)/10")
                                    .font(.system(size: 10, weight: .semibold))
                            }
                            .foregroundColor(confidenceColor(conf))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(confidenceColor(conf).opacity(0.15))
                            .cornerRadius(4)
                        }

                        // Domain
                        if let domain = decision["domain"] as? String, !domain.isEmpty {
                            Text(domain)
                                .font(.system(size: 10))
                                .foregroundColor(.secondary)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 1)
                                .background(.quaternary)
                                .cornerRadius(3)
                        }

                        // Status
                        let status = decision["status"] as? String ?? "tracked"
                        Text(status)
                            .font(.system(size: 10, weight: .medium))
                            .foregroundColor(status == "evaluated" ? .green : .orange)

                        Spacer()

                        // Date
                        if let date = decision["created_at"] as? String {
                            Text(String(date.prefix(10)))
                                .font(.system(size: 10))
                                .foregroundColor(.secondary)
                        }
                    }

                    // Reasoning
                    if let reasoning = decision["reasoning"] as? String, !reasoning.isEmpty {
                        Text(reasoning)
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                            .lineLimit(2)
                    }

                    // Made by
                    if let madeBy = decision["made_by"] as? String, !madeBy.isEmpty {
                        Text("By: \(madeBy)")
                            .font(.system(size: 11))
                            .foregroundColor(.secondary.opacity(0.7))
                    }

                    // Outcome (if evaluated)
                    if let outcome = decision["outcome"] as? String, !outcome.isEmpty {
                        HStack(spacing: 4) {
                            Image(systemName: (decision["was_correct"] as? Bool == true) ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .font(.system(size: 10))
                                .foregroundColor((decision["was_correct"] as? Bool == true) ? .green : .red)
                            Text("Outcome: \(outcome)")
                                .font(.system(size: 11))
                                .foregroundColor(.secondary)
                        }
                    }

                    // Evaluation date
                    if let evalDate = decision["evaluation_date"] as? String, !evalDate.isEmpty,
                       (decision["status"] as? String) == "tracked" {
                        Text("Evaluate by: \(evalDate)")
                            .font(.system(size: 10))
                            .foregroundColor(.secondary.opacity(0.6))
                    }
                }
            }
        }
        .padding(12)
        .background(.quaternary.opacity(0.3))
        .cornerRadius(8)
    }

    private func confidenceColor(_ conf: Int) -> Color {
        if conf >= 8 { return .green }
        if conf >= 5 { return .blue }
        return .orange
    }
}
