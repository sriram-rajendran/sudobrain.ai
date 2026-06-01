import SwiftUI

struct MainAppView: View {
    @ObservedObject var recorder: AudioRecorder
    @ObservedObject var appState: AppState
    @State private var selectedSection: AppState.SidebarSection? = .today

    var body: some View {
        NavigationSplitView {
            sidebarContent
        } detail: {
            detailForSection(selectedSection ?? .today)
                .id(selectedSection)
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                recordButton
                Button(action: { selectedSection = .search }) {
                    Image(systemName: "magnifyingglass")
                }
                .keyboardShortcut("k", modifiers: .command)
            }
        }
    }

    private var sidebarContent: some View {
        VStack(spacing: 0) {
            List(selection: $selectedSection) {
                ForEach(sectionsFor(.main)) { section in
                    sidebarRow(section)
                }

                Section("Knowledge") {
                    ForEach(sectionsFor(.knowledge)) { section in
                        sidebarRow(section)
                    }
                }

                Section("Integrations") {
                    ForEach(sectionsFor(.integrations)) { section in
                        sidebarRow(section)
                    }
                }

                Section("Personal") {
                    ForEach(sectionsFor(.personal)) { section in
                        sidebarRow(section)
                    }
                }
            }
            .listStyle(.sidebar)

            // Context & recording indicators
            VStack(spacing: 0) {
                if ContextEngine.shared.isFocusMode {
                    HStack(spacing: 6) {
                        Image(systemName: "moon.fill")
                            .font(.system(size: 9))
                            .foregroundColor(.purple)
                        Text("Focus Mode")
                            .font(.system(size: 10, weight: .medium))
                            .foregroundColor(.purple)
                        Spacer()
                        Text(ContextEngine.shared.activeApp)
                            .font(.system(size: 9))
                            .foregroundColor(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 6)
                    .background(.purple.opacity(0.1))
                } else if !ContextEngine.shared.activeApp.isEmpty {
                    HStack(spacing: 6) {
                        Circle()
                            .fill(contextColor)
                            .frame(width: 5, height: 5)
                        Text(ContextEngine.shared.activeApp)
                            .font(.system(size: 10))
                            .foregroundColor(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 4)
                }

                if recorder.isRecording {
                    HStack(spacing: 6) {
                        Circle().fill(.red).frame(width: 6, height: 6)
                        Text("Recording")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.red)
                        Spacer()
                        Text(formatDuration(recorder.recordingDuration))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(.ultraThinMaterial)
                }
            }
        }
        .frame(minWidth: 180)
    }

    private func sidebarRow(_ section: AppState.SidebarSection) -> some View {
        Label(section.label, systemImage: section.icon)
            .tag(section)
    }

    private func sectionsFor(_ group: AppState.SidebarGroup) -> [AppState.SidebarSection] {
        AppState.SidebarSection.allCases.filter { $0.group == group }
    }

    @ViewBuilder
    private func detailForSection(_ section: AppState.SidebarSection) -> some View {
        switch section {
        case .today:
            TodayView(recorder: recorder)
        case .onboarding:
            OnboardingView()
        case .search:
            SearchView()
        case .chat:
            ChatView()
        case .inbox:
            InboxView()
        case .intelligence:
            IntelligenceView()
        case .meetings:
            MeetingsView()
        case .people:
            PeopleView()
        case .decisions:
            DecisionsView()
        case .tasks:
            TasksView()
        case .promises:
            PromisesView()
        case .review:
            KnowledgeReviewView()
        case .crossReferences:
            CrossReferencesView()
        case .documents:
            DocumentsView()
        case .workflows:
            WorkflowsView()
        case .reports:
            ReportsView()
        case .sync:
            SourceSyncView()
        case .slack:
            SlackView()
        case .gmail:
            GmailView()
        case .calendar:
            CalendarView()
        case .linear:
            LinearView()
        case .graph:
            GraphView()
        case .models:
            ModelsView()
        case .health:
            HealthDataView()
        case .admin:
            AdminDebugView()
        case .localSettings:
            LocalSettingsView()
        case .habits:
            HabitsView()
        case .expenses:
            ExpensesView()
        case .ideas:
            IdeasView()
        }
    }

    @ViewBuilder
    private var recordButton: some View {
        if recorder.isRecording {
            Button(action: { recorder.stopRecording() }) {
                HStack(spacing: 4) {
                    Circle().fill(.red).frame(width: 6, height: 6)
                    Text(formatDuration(recorder.recordingDuration))
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(.red)
                    Image(systemName: "stop.fill")
                        .font(.system(size: 8))
                        .foregroundColor(.red)
                }
            }
            .keyboardShortcut("r", modifiers: .command)
        } else {
            Button(action: { recorder.startRecording() }) {
                Image(systemName: "record.circle")
            }
            .keyboardShortcut("r", modifiers: .command)
        }
    }

    private var contextColor: Color {
        switch ContextEngine.shared.contextMode {
        case .meeting: return .red
        case .deepWork: return .green
        case .communication: return .blue
        case .browsing: return .orange
        case .idle: return .secondary
        }
    }

    private func formatDuration(_ d: TimeInterval) -> String {
        let m = Int(d) / 60
        let s = Int(d) % 60
        return String(format: "%d:%02d", m, s)
    }
}
