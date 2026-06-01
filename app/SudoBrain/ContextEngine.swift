import AppKit
import Foundation

/// Tracks active app, detects focus mode, manages context awareness.
class ContextEngine: ObservableObject {
    static let shared = ContextEngine()

    @Published var activeApp: String = ""
    @Published var activeAppBundleId: String = ""
    @Published var isFocusMode: Bool = false
    @Published var focusDuration: TimeInterval = 0
    @Published var contextMode: ContextMode = .idle

    enum ContextMode: String {
        case idle
        case meeting       // Zoom/Teams/Meet detected
        case deepWork      // Same app > 30 min
        case communication // Mail/Slack/Messages
        case browsing      // Browser active
    }

    private var focusStartTime: Date?
    private var lastAppChange: Date = Date()
    private var focusTimer: Timer?
    private var currentFocusApp: String = ""

    // Apps that indicate meeting
    private let meetingApps = ["zoom.us", "com.microsoft.teams", "com.google.Chrome"]
    private let commApps = ["com.apple.mail", "com.tinyspeck.slackmacgap", "com.apple.MobileSMS"]
    private let browserApps = ["com.google.Chrome", "com.apple.Safari", "ai.perplexity.comet"]
    private let codeApps = ["com.microsoft.VSCode", "com.apple.dt.Xcode", "com.googlecode.iterm2"]

    private init() {
        startTracking()
    }

    func startTracking() {
        // Observe app activation changes
        NSWorkspace.shared.notificationCenter.addObserver(
            self, selector: #selector(appDidActivate(_:)),
            name: NSWorkspace.didActivateApplicationNotification, object: nil
        )

        // Update timer for focus duration
        focusTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            self?.updateFocusState()
        }

        // Set initial state
        if let frontApp = NSWorkspace.shared.frontmostApplication {
            activeApp = frontApp.localizedName ?? ""
            activeAppBundleId = frontApp.bundleIdentifier ?? ""
            currentFocusApp = activeApp
            lastAppChange = Date()
        }
    }

    @objc private func appDidActivate(_ notification: Notification) {
        guard let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }

        let newApp = app.localizedName ?? ""
        let newBundle = app.bundleIdentifier ?? ""

        if newApp != activeApp {
            // App changed — reset focus if different app
            if newApp != currentFocusApp {
                currentFocusApp = newApp
                focusStartTime = Date()
                isFocusMode = false
                focusDuration = 0
            }
            lastAppChange = Date()
        }

        DispatchQueue.main.async {
            self.activeApp = newApp
            self.activeAppBundleId = newBundle
            self.contextMode = self.classifyMode(newBundle)
        }
    }

    private func updateFocusState() {
        guard let start = focusStartTime else {
            focusStartTime = Date()
            return
        }

        let elapsed = Date().timeIntervalSince(start)
        let sinceLastChange = Date().timeIntervalSince(lastAppChange)

        DispatchQueue.main.async {
            self.focusDuration = sinceLastChange

            // Focus mode: same app for > 30 minutes
            if sinceLastChange > 1800 && !self.isFocusMode {
                self.isFocusMode = true
            }

            // Exit focus mode if app changed recently
            if sinceLastChange < 60 {
                self.isFocusMode = false
            }
        }
    }

    private func classifyMode(_ bundleId: String) -> ContextMode {
        if meetingApps.contains(where: { bundleId.contains($0) }) { return .meeting }
        if codeApps.contains(where: { bundleId.contains($0) }) { return .deepWork }
        if commApps.contains(where: { bundleId.contains($0) }) { return .communication }
        if browserApps.contains(where: { bundleId.contains($0) }) { return .browsing }
        return .idle
    }

    /// Should we suppress this notification based on context?
    func shouldSuppressNotification(priority: String) -> Bool {
        if isFocusMode && priority != "urgent" {
            return true
        }
        if contextMode == .meeting && priority != "urgent" {
            return true
        }
        return false
    }
}
