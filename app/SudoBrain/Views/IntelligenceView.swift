import SwiftUI

/// Intelligence dashboard — surfaces all backend intelligence features.
/// Cards: overload, focus, trust map, relationship decay, customer pulse,
/// project risk, silent projects, bus factor, recurring problems, anomalies,
/// meeting ROI/rot, plus self-score for the system itself.
struct IntelligenceView: View {
    @StateObject private var vm = IntelligenceVM()

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 16) {
                header
                if vm.loading {
                    ProgressView("Loading intelligence…")
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.top, 60)
                } else {
                    overloadCard
                    HStack(alignment: .top, spacing: 16) {
                        focusCard
                        meetingRotCard
                    }
                    HStack(alignment: .top, spacing: 16) {
                        relationshipDecayCard
                        customerPulseCard
                    }
                    projectRiskCard
                    HStack(alignment: .top, spacing: 16) {
                        silentProjectsCard
                        busFactorCard
                    }
                    recurringProblemsCard
                    HStack(alignment: .top, spacing: 16) {
                        anomaliesCard
                        emergingTopicsCard
                    }
                    trustMapCard
                    selfScoreCard
                }
            }
            .padding(20)
        }
        .navigationTitle("Intelligence")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await vm.runAll() }
                } label: {
                    Label("Run all", systemImage: "play.circle")
                }
                .help("Trigger all intelligence jobs now")
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await vm.refresh() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
        .task { await vm.refresh() }
    }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Intelligence")
                .font(.largeTitle).bold()
            Text("Derived signals from your work — refreshed " + (vm.lastRefreshed ?? "—"))
                .font(.subheadline).foregroundStyle(.secondary)
        }
    }

    // MARK: - Cards

    private var overloadCard: some View {
        IntelCard(title: "Overload Score", icon: "gauge.with.dots.needle.bottom.50percent", tint: vm.overloadColor) {
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(Int(vm.overloadScore))")
                        .font(.system(size: 56, weight: .heavy, design: .rounded))
                        .foregroundStyle(vm.overloadColor)
                    Text(vm.overloadVerdict.uppercased())
                        .font(.caption2).bold()
                        .foregroundStyle(vm.overloadColor)
                }
                .frame(width: 120)

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(vm.overloadFactors, id: \.factor) { f in
                        HStack {
                            Text(f.factor.replacingOccurrences(of: "_", with: " "))
                                .font(.caption).bold()
                            Spacer()
                            Text("\(Int(f.score))/100")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        ProgressView(value: f.score, total: 100)
                            .tint(vm.overloadColor)
                        Text(f.description)
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var focusCard: some View {
        IntelCard(title: "Focus / Fragmentation", icon: "scope", tint: .blue) {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(Int(vm.focusAvgScore))")
                        .font(.system(size: 36, weight: .bold, design: .rounded))
                    Text("/100 avg")
                        .foregroundStyle(.secondary)
                }
                Text("\(vm.focusActiveDays) active days · \(vm.focusAvgSwitches) avg switches/day")
                    .font(.caption).foregroundStyle(.secondary)
                if let best = vm.focusBest, let worst = vm.focusWorst {
                    HStack {
                        Label("\(best.date) (\(Int(best.score)))", systemImage: "star.fill")
                            .foregroundStyle(.green)
                        Spacer()
                        Label("\(worst.date) (\(Int(worst.score)))", systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                    }
                    .font(.caption2)
                }
            }
        }
    }

    private var meetingRotCard: some View {
        IntelCard(title: "Meeting Rot", icon: "person.3.sequence", tint: .purple) {
            VStack(alignment: .leading, spacing: 6) {
                if vm.meetingRot.isEmpty {
                    Text("No recurring meetings detected")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    ForEach(vm.meetingRot.prefix(5), id: \.title) { m in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(m.title).font(.caption).bold()
                                Text("\(m.instances)× · \(m.totalPersonMinutes)pm")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if m.rotWarning {
                                Text("ROT").font(.caption2).bold()
                                    .padding(.horizontal, 6).padding(.vertical, 2)
                                    .background(Color.red.opacity(0.2))
                                    .foregroundStyle(.red)
                                    .clipShape(Capsule())
                            }
                        }
                    }
                }
            }
        }
    }

    private var relationshipDecayCard: some View {
        IntelCard(title: "Relationship Decay", icon: "person.crop.circle.badge.exclamationmark", tint: .orange) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(vm.decayFlagged.count) cooling/silent")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(vm.decayFlagged.prefix(6), id: \.name) { p in
                    HStack {
                        Text(p.name).font(.caption)
                        Spacer()
                        Text(p.trend.uppercased())
                            .font(.caption2)
                            .foregroundStyle(p.trend == "cooling" ? .orange : .secondary)
                        if let d = p.daysSince {
                            Text("\(d)d")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
    }

    private var customerPulseCard: some View {
        IntelCard(title: "Customer Pulse", icon: "antenna.radiowaves.left.and.right", tint: .pink) {
            VStack(alignment: .leading, spacing: 6) {
                if vm.customerOrgs.isEmpty {
                    Text("No external orgs detected")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    ForEach(vm.customerOrgs.prefix(6), id: \.domain) { o in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(o.domain).font(.caption).bold()
                                Text("\(o.totalEmails) emails · last \(o.daysSince ?? 0)d ago")
                                    .font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(o.status.uppercased())
                                .font(.caption2).bold()
                                .foregroundStyle(statusColor(o.status))
                        }
                    }
                }
            }
        }
    }

    private var projectRiskCard: some View {
        IntelCard(title: "Project Risk", icon: "exclamationmark.triangle.fill", tint: .red) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(vm.projectsByRisk.prefix(7), id: \.project) { p in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(p.project).font(.caption).bold()
                            Text("\(p.openIssues) open · \(p.overdue) overdue · \(Int(p.closeRate14d * 100))% close rate")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text("\(Int(p.riskScore))")
                            .font(.system(.body, design: .rounded)).bold()
                            .foregroundStyle(riskColor(p.riskScore))
                    }
                    Divider()
                }
            }
        }
    }

    private var silentProjectsCard: some View {
        IntelCard(title: "Silent Projects", icon: "moon.zzz", tint: .indigo) {
            VStack(alignment: .leading, spacing: 6) {
                if vm.silentProjects.isEmpty {
                    Text("All projects active").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(vm.silentProjects.prefix(6), id: \.project) { p in
                    HStack {
                        Text(p.project).font(.caption)
                        Spacer()
                        Text("\(p.daysSilent)d silent")
                            .font(.caption2).foregroundStyle(.orange)
                    }
                }
            }
        }
    }

    private var busFactorCard: some View {
        IntelCard(title: "Bus Factor Risk", icon: "person.fill.questionmark", tint: .yellow) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(vm.busFactorHigh.count) projects with single point of knowledge")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(vm.busFactorHigh.prefix(6), id: \.project) { b in
                    HStack {
                        Text(b.project).font(.caption)
                        Spacer()
                        Text(b.topExpert ?? "—")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var recurringProblemsCard: some View {
        IntelCard(title: "Recurring Problems", icon: "arrow.triangle.2.circlepath", tint: .teal) {
            VStack(alignment: .leading, spacing: 8) {
                Text("\(vm.recurringClusters.count) clusters spanning multiple projects/sources")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(vm.recurringClusters.prefix(5), id: \.id) { c in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text("size \(c.size)").font(.caption2).bold()
                            Text(c.projects.joined(separator: " · "))
                                .font(.caption2).foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        ForEach(c.samples.prefix(3), id: \.self) { s in
                            Text("• " + s).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                    Divider()
                }
            }
        }
    }

    private var anomaliesCard: some View {
        IntelCard(title: "Anomalies", icon: "bolt.heart", tint: .mint) {
            VStack(alignment: .leading, spacing: 6) {
                if vm.anomalies.isEmpty {
                    Text("No anomalies in last 30 days")
                        .font(.caption).foregroundStyle(.secondary)
                }
                ForEach(vm.anomalies.prefix(8), id: \.id) { a in
                    HStack {
                        Text("\(a.date)").font(.caption2).foregroundStyle(.secondary)
                        Text(a.metric).font(.caption2)
                        Spacer()
                        Text("\(a.value)")
                            .font(.caption2).bold()
                        Text("(z=\(String(format: "%.1f", a.zScore)))")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    private var emergingTopicsCard: some View {
        IntelCard(title: "Emerging Topics (7d)", icon: "sparkles", tint: .green) {
            VStack(alignment: .leading, spacing: 4) {
                if vm.emergingTerms.isEmpty {
                    Text("No emerging topics").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(vm.emergingTerms.prefix(10), id: \.term) { t in
                    HStack {
                        Text(t.term).font(.caption).bold()
                        Spacer()
                        Text("\(t.recentCount)×").font(.caption2)
                        Text("(\(t.ratioLabel))")
                            .font(.caption2).foregroundStyle(.green)
                    }
                }
            }
        }
    }

    private var trustMapCard: some View {
        IntelCard(title: "Trust Map (Promise Tracking)", icon: "checklist", tint: .cyan) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(vm.trustEntries.count) people · \(vm.trustTotalPromises) promises · \(vm.trustTotalOverdue) overdue")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(vm.trustEntries.prefix(8), id: \.name) { e in
                    HStack {
                        Text(e.name).font(.caption)
                        Spacer()
                        Text("\(e.pending) pending")
                            .font(.caption2).foregroundStyle(.secondary)
                        if e.overdue > 0 {
                            Text("\(e.overdue) overdue")
                                .font(.caption2)
                                .foregroundStyle(.red)
                        }
                    }
                }
            }
        }
    }

    private var selfScoreCard: some View {
        IntelCard(title: "System Self-Score", icon: "brain.head.profile", tint: .gray) {
            VStack(alignment: .leading, spacing: 6) {
                Text("\(vm.selfScoreFeatures.count) features tracked")
                    .font(.caption).foregroundStyle(.secondary)
                ForEach(vm.selfScoreFeatures, id: \.feature) { f in
                    HStack {
                        Text(f.feature.replacingOccurrences(of: "_", with: " "))
                            .font(.caption)
                        Spacer()
                        Text("\(f.totalFlags) flags")
                            .font(.caption2).foregroundStyle(.secondary)
                        if let p = f.precision {
                            Text("\(Int(p * 100))%")
                                .font(.caption2)
                                .foregroundStyle(p > 0.6 ? .green : .orange)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Helpers

    private func statusColor(_ s: String) -> Color {
        switch s {
        case "going_quiet", "cooling": return .orange
        case "silent": return .gray
        case "active", "new": return .green
        default: return .secondary
        }
    }

    private func riskColor(_ r: Double) -> Color {
        if r >= 70 { return .red }
        if r >= 50 { return .orange }
        if r >= 30 { return .yellow }
        return .green
    }
}

// MARK: - Reusable card

private struct IntelCard<Content: View>: View {
    let title: String
    let icon: String
    let tint: Color
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: icon).foregroundStyle(tint)
                Text(title).font(.headline)
            }
            content()
        }
        .padding(16)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(tint.opacity(0.2), lineWidth: 1)
        )
    }
}

// MARK: - View Model

@MainActor
class IntelligenceVM: ObservableObject {
    @Published var loading = false
    @Published var lastRefreshed: String?

    // Overload
    @Published var overloadScore: Double = 0
    @Published var overloadVerdict: String = "—"
    @Published var overloadFactors: [OverloadFactor] = []

    // Focus
    @Published var focusAvgScore: Double = 0
    @Published var focusActiveDays: Int = 0
    @Published var focusAvgSwitches: Double = 0
    @Published var focusBest: FocusDay?
    @Published var focusWorst: FocusDay?

    // Decay
    @Published var decayFlagged: [DecayPerson] = []

    // Customer
    @Published var customerOrgs: [CustomerOrg] = []

    // Project risk
    @Published var projectsByRisk: [ProjectRisk] = []

    // Silent / bus factor
    @Published var silentProjects: [SilentProject] = []
    @Published var busFactorHigh: [BusFactorEntry] = []

    // Recurring
    @Published var recurringClusters: [Cluster] = []

    // Anomalies / emerging
    @Published var anomalies: [Anomaly] = []
    @Published var emergingTerms: [EmergingTerm] = []

    // Trust
    @Published var trustEntries: [TrustEntry] = []
    @Published var trustTotalPromises: Int = 0
    @Published var trustTotalOverdue: Int = 0

    // Self-score
    @Published var selfScoreFeatures: [SelfScoreFeature] = []

    // Meeting rot
    @Published var meetingRot: [MeetingRotEntry] = []

    var overloadColor: Color {
        if overloadScore >= 75 { return .red }
        if overloadScore >= 55 { return .orange }
        if overloadScore >= 35 { return .yellow }
        return .green
    }

    func refresh() async {
        loading = true
        defer { loading = false }
        async let a = loadOverload()
        async let b = loadFocus()
        async let c = loadDecay()
        async let d = loadCustomerPulse()
        async let e = loadProjectRisk()
        async let f = loadSilentProjects()
        async let g = loadBusFactor()
        async let h = loadRecurring()
        async let i = loadAnomalies()
        async let j = loadEmerging()
        async let k = loadTrust()
        async let l = loadSelfScore()
        async let m = loadMeetingRot()
        _ = await (a, b, c, d, e, f, g, h, i, j, k, l, m)
        let f2 = DateFormatter()
        f2.dateFormat = "HH:mm"
        lastRefreshed = f2.string(from: Date())
    }

    func runAll() async {
        do {
            _ = try await APIClient.shared.post("/intelligence/run-now?group=all", body: [:], timeout: 600)
            await refresh()
        } catch {
            print("runAll failed: \(error)")
        }
    }

    // MARK: - Loaders

    private func loadOverload() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/overload")
            overloadScore = d["score"] as? Double ?? 0
            overloadVerdict = d["verdict"] as? String ?? "—"
            if let factors = d["factors"] as? [String: [String: Any]] {
                overloadFactors = factors.map { (k, v) in
                    OverloadFactor(
                        factor: k,
                        score: v["score"] as? Double ?? 0,
                        weight: v["weight"] as? Double ?? 0,
                        description: v["description"] as? String ?? ""
                    )
                }.sorted { $0.score * $0.weight > $1.score * $1.weight }
            }
        } catch { print("overload: \(error)") }
    }

    private func loadFocus() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/focus?days=14")
            focusAvgScore = d["avg_focus_score"] as? Double ?? 0
            focusActiveDays = d["active_days"] as? Int ?? 0
            focusAvgSwitches = d["avg_context_switches"] as? Double ?? 0
            if let best = d["best_day"] as? [String: Any] {
                focusBest = FocusDay(date: best["date"] as? String ?? "", score: best["score"] as? Double ?? 0)
            }
            if let worst = d["worst_day"] as? [String: Any] {
                focusWorst = FocusDay(date: worst["date"] as? String ?? "", score: worst["score"] as? Double ?? 0)
            }
        } catch { print("focus: \(error)") }
    }

    private func loadDecay() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/relationship-decay")
            if let flagged = d["flagged"] as? [[String: Any]] {
                decayFlagged = flagged.compactMap { row in
                    DecayPerson(
                        name: row["name"] as? String ?? "",
                        trend: row["trend"] as? String ?? "",
                        daysSince: row["days_since"] as? Int
                    )
                }
            }
        } catch { print("decay: \(error)") }
    }

    private func loadCustomerPulse() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/customer-pulse")
            if let orgs = d["organizations"] as? [[String: Any]] {
                customerOrgs = orgs.map { row in
                    CustomerOrg(
                        domain: row["domain"] as? String ?? "",
                        totalEmails: row["total_emails"] as? Int ?? 0,
                        daysSince: row["days_since"] as? Int,
                        status: row["status"] as? String ?? ""
                    )
                }
            }
        } catch { print("customerPulse: \(error)") }
    }

    private func loadProjectRisk() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/project-risk")
            if let all = d["all"] as? [[String: Any]] {
                projectsByRisk = all.map { row in
                    ProjectRisk(
                        project: row["project"] as? String ?? "",
                        openIssues: row["open_issues"] as? Int ?? 0,
                        overdue: row["overdue"] as? Int ?? 0,
                        closeRate14d: row["close_rate_14d"] as? Double ?? 0,
                        riskScore: row["risk_score"] as? Double ?? 0
                    )
                }
            }
        } catch { print("projectRisk: \(error)") }
    }

    private func loadSilentProjects() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/silent-projects")
            if let flagged = d["flagged"] as? [[String: Any]] {
                silentProjects = flagged.map { row in
                    SilentProject(
                        project: row["project"] as? String ?? "",
                        daysSilent: row["days_silent"] as? Int ?? 0,
                        openIssues: row["open_issues"] as? Int ?? 0
                    )
                }
            }
        } catch { print("silent: \(error)") }
    }

    private func loadBusFactor() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/bus-factor")
            if let high = d["high_risk"] as? [[String: Any]] {
                busFactorHigh = high.map { row in
                    BusFactorEntry(
                        project: row["project"] as? String ?? "",
                        topExpert: row["top_expert"] as? String
                    )
                }
            }
        } catch { print("busFactor: \(error)") }
    }

    private func loadRecurring() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/recurring-problems?min_cluster_size=4")
            if let clusters = d["clusters"] as? [[String: Any]] {
                recurringClusters = clusters.enumerated().map { (i, row) in
                    let div = row["diversity"] as? [String: Any] ?? [:]
                    let projects = (div["projects"] as? [String]) ?? []
                    let members = (row["members"] as? [[String: Any]]) ?? []
                    let samples = members.compactMap { $0["text"] as? String }
                    return Cluster(
                        id: i,
                        size: row["cluster_size"] as? Int ?? 0,
                        projects: projects,
                        samples: samples
                    )
                }
            }
        } catch { print("recurring: \(error)") }
    }

    private func loadAnomalies() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/anomalies?days=30&sigma=2")
            if let an = d["anomalies"] as? [[String: Any]] {
                anomalies = an.enumerated().map { (i, row) in
                    Anomaly(
                        id: i,
                        date: row["date"] as? String ?? "",
                        metric: row["metric"] as? String ?? "",
                        value: row["value"] as? Int ?? 0,
                        zScore: row["z_score"] as? Double ?? 0
                    )
                }
            }
        } catch { print("anomalies: \(error)") }
    }

    private func loadEmerging() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/emerging-topics?window_days=7")
            if let terms = d["emerging_terms"] as? [[String: Any]] {
                emergingTerms = terms.compactMap { row in
                    let term = row["term"] as? String ?? ""
                    // Skip obvious noise (Slack user IDs)
                    if term.hasPrefix("u0") && term.count >= 9 { return nil }
                    let recent = row["recent_count"] as? Int ?? 0
                    let ratio = row["ratio"]
                    let label: String
                    if let r = ratio as? Double { label = "\(String(format: "%.1f", r))×" }
                    else if let s = ratio as? String { label = s }
                    else { label = "?" }
                    return EmergingTerm(term: term, recentCount: recent, ratioLabel: label)
                }
            }
        } catch { print("emerging: \(error)") }
    }

    private func loadTrust() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/trust-map?min_sample=2")
            trustTotalPromises = d["total_promises"] as? Int ?? 0
            trustTotalOverdue = d["total_overdue"] as? Int ?? 0
            if let entries = d["entries"] as? [[String: Any]] {
                trustEntries = entries.map { row in
                    TrustEntry(
                        name: row["name"] as? String ?? "",
                        total: row["total_promises"] as? Int ?? 0,
                        pending: row["pending"] as? Int ?? 0,
                        overdue: row["overdue"] as? Int ?? 0
                    )
                }
            }
        } catch { print("trust: \(error)") }
    }

    private func loadSelfScore() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/self-score")
            if let features = d["features"] as? [[String: Any]] {
                selfScoreFeatures = features.map { row in
                    SelfScoreFeature(
                        feature: row["feature"] as? String ?? "",
                        totalFlags: row["total_flags"] as? Int ?? 0,
                        precision: row["precision"] as? Double
                    )
                }
            }
        } catch { print("selfScore: \(error)") }
    }

    private func loadMeetingRot() async {
        do {
            let d = try await APIClient.shared.getRawObject("/intelligence/meeting-rot")
            if let m = d["meetings"] as? [[String: Any]] {
                meetingRot = m.map { row in
                    MeetingRotEntry(
                        title: row["title"] as? String ?? "",
                        instances: row["instances"] as? Int ?? 0,
                        totalPersonMinutes: row["total_person_minutes"] as? Int ?? 0,
                        rotWarning: row["rot_warning"] as? Bool ?? false
                    )
                }
            }
        } catch { print("meetingRot: \(error)") }
    }
}

// MARK: - Models

struct OverloadFactor { let factor: String; let score: Double; let weight: Double; let description: String }
struct FocusDay { let date: String; let score: Double }
struct DecayPerson { let name: String; let trend: String; let daysSince: Int? }
struct CustomerOrg { let domain: String; let totalEmails: Int; let daysSince: Int?; let status: String }
struct ProjectRisk { let project: String; let openIssues: Int; let overdue: Int; let closeRate14d: Double; let riskScore: Double }
struct SilentProject { let project: String; let daysSilent: Int; let openIssues: Int }
struct BusFactorEntry { let project: String; let topExpert: String? }
struct Cluster { let id: Int; let size: Int; let projects: [String]; let samples: [String] }
struct Anomaly { let id: Int; let date: String; let metric: String; let value: Int; let zScore: Double }
struct EmergingTerm { let term: String; let recentCount: Int; let ratioLabel: String }
struct TrustEntry { let name: String; let total: Int; let pending: Int; let overdue: Int }
struct SelfScoreFeature { let feature: String; let totalFlags: Int; let precision: Double? }
struct MeetingRotEntry { let title: String; let instances: Int; let totalPersonMinutes: Int; let rotWarning: Bool }
