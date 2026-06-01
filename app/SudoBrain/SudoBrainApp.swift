import SwiftUI

@main
struct SudoBrainApp: App {
    @StateObject private var audioRecorder = AudioRecorder()
    @StateObject private var appState = AppState()

    init() {
        BackendManager.shared.start()
    }

    var body: some Scene {
        // Main application window
        WindowGroup {
            MainAppView(recorder: audioRecorder, appState: appState)
                .frame(minWidth: 800, minHeight: 500)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unifiedCompact)
        .defaultSize(width: 1100, height: 700)

        // Menu bar quick-access (secondary)
        MenuBarExtra("SudoBrain", systemImage: audioRecorder.isRecording ? "record.circle.fill" : "brain.head.profile") {
            MenuBarView(recorder: audioRecorder)
        }
        .menuBarExtraStyle(.window)

        // Settings
        Settings {
            SettingsView()
        }
    }
}
