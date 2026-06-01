import Foundation

/// Shared enum for due date display across views.
enum DueType { case today, overdue, upcoming }

/// Shared app state across views.
class AppState: ObservableObject {
    @Published var selectedSection: SidebarSection? = .today
    @Published var searchText: String = ""

    enum SidebarSection: String, CaseIterable, Identifiable {
        case today
        case chat
        case inbox
        case intelligence

        // Knowledge
        case meetings
        case people
        case decisions
        case tasks

        // Integrations
        case slack
        case graph

        // Personal
        case habits
        case expenses
        case ideas

        var id: String { rawValue }

        var label: String {
            switch self {
            case .today: return "Today"
            case .chat: return "Chat"
            case .inbox: return "Inbox"
            case .intelligence: return "Intelligence"
            case .meetings: return "Meetings"
            case .people: return "People"
            case .decisions: return "Decisions"
            case .tasks: return "Tasks"
            case .slack: return "Slack"
            case .graph: return "Knowledge Graph"
            case .habits: return "Habits"
            case .expenses: return "Expenses"
            case .ideas: return "Ideas"
            }
        }

        var icon: String {
            switch self {
            case .today: return "calendar.badge.clock"
            case .chat: return "bubble.left.and.bubble.right"
            case .inbox: return "tray"
            case .intelligence: return "brain"
            case .meetings: return "person.3"
            case .people: return "person.circle"
            case .decisions: return "arrow.triangle.branch"
            case .tasks: return "checkmark.circle"
            case .slack: return "message.badge"
            case .graph: return "network"
            case .habits: return "chart.bar"
            case .expenses: return "indianrupeesign.circle"
            case .ideas: return "lightbulb"
            }
        }

        var group: SidebarGroup {
            switch self {
            case .today, .chat, .inbox, .intelligence: return .main
            case .meetings, .people, .decisions, .tasks: return .knowledge
            case .slack, .graph: return .integrations
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
