import Foundation

/// Shared enum for due date display across views.
enum DueType { case today, overdue, upcoming }

/// Shared app state across views.
class AppState: ObservableObject {
    @Published var selectedSection: SidebarSection? = .today
    @Published var searchText: String = ""

    enum SidebarSection: String, CaseIterable, Identifiable {
        case today
        case search
        case chat
        case inbox
        case intelligence

        // Knowledge
        case meetings
        case people
        case decisions
        case tasks
        case documents
        case workflows
        case reports

        // Integrations
        case sync
        case slack
        case gmail
        case calendar
        case linear
        case graph
        case models
        case health

        // Personal
        case habits
        case expenses
        case ideas

        var id: String { rawValue }

        var label: String {
            switch self {
            case .today: return "Today"
            case .search: return "Search"
            case .chat: return "Chat"
            case .inbox: return "Inbox"
            case .intelligence: return "Intelligence"
            case .meetings: return "Meetings"
            case .people: return "People"
            case .decisions: return "Decisions"
            case .tasks: return "Tasks"
            case .documents: return "Documents"
            case .workflows: return "Workflows"
            case .reports: return "Reports"
            case .sync: return "Source Sync"
            case .slack: return "Slack"
            case .gmail: return "Gmail"
            case .calendar: return "Calendar"
            case .linear: return "Linear"
            case .graph: return "Knowledge Graph"
            case .models: return "Models"
            case .health: return "Health"
            case .habits: return "Habits"
            case .expenses: return "Expenses"
            case .ideas: return "Ideas"
            }
        }

        var icon: String {
            switch self {
            case .today: return "calendar.badge.clock"
            case .search: return "magnifyingglass"
            case .chat: return "bubble.left.and.bubble.right"
            case .inbox: return "tray"
            case .intelligence: return "brain"
            case .meetings: return "person.3"
            case .people: return "person.circle"
            case .decisions: return "arrow.triangle.branch"
            case .tasks: return "checkmark.circle"
            case .documents: return "doc.text"
            case .workflows: return "point.3.connected.trianglepath.dotted"
            case .reports: return "chart.line.uptrend.xyaxis"
            case .sync: return "arrow.triangle.2.circlepath"
            case .slack: return "message.badge"
            case .gmail: return "envelope"
            case .calendar: return "calendar"
            case .linear: return "list.bullet.rectangle"
            case .graph: return "network"
            case .models: return "cpu"
            case .health: return "heart"
            case .habits: return "chart.bar"
            case .expenses: return "indianrupeesign.circle"
            case .ideas: return "lightbulb"
            }
        }

        var group: SidebarGroup {
            switch self {
            case .today, .search, .chat, .inbox, .intelligence: return .main
            case .meetings, .people, .decisions, .tasks, .documents, .workflows, .reports: return .knowledge
            case .sync, .slack, .gmail, .calendar, .linear, .graph, .models, .health: return .integrations
            case .habits, .expenses, .ideas: return .personal
            }
        }
    }

    enum SidebarGroup: String, CaseIterable {
        case main
        case knowledge
        case integrations
        case personal

        var label: String? {
            switch self {
            case .main: return nil
            case .knowledge: return "Knowledge"
            case .integrations: return "Integrations"
            case .personal: return "Personal"
            }
        }
    }
}
