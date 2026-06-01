import Foundation

/// Manages the Python backend server lifecycle.
/// Starts uvicorn on app launch, stops it on quit.
class BackendManager {
    static let shared = BackendManager()

    private var process: Process?
    private let port = 8420

    private init() {}

    /// Start the Python backend server if not already running.
    func start() {
        // Check if already running
        if isRunning() {
            print("[Backend] Already running on port \(port)")
            return
        }

        let projectDir = findProjectDir()
        guard let projectDir = projectDir else {
            print("[Backend] Could not find project directory")
            return
        }

        let venvPython = projectDir.appendingPathComponent(".venv/bin/python").path

        guard FileManager.default.fileExists(atPath: venvPython) else {
            print("[Backend] Python venv not found at \(venvPython)")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: venvPython)
        process.arguments = ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "\(port)"]
        process.currentDirectoryURL = projectDir
        process.environment = ProcessInfo.processInfo.environment

        // Suppress output in production; log in debug
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        pipe.fileHandleForReading.readabilityHandler = { handle in
            if let line = String(data: handle.availableData, encoding: .utf8), !line.isEmpty {
                print("[Backend] \(line.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }

        process.terminationHandler = { proc in
            print("[Backend] Process terminated with status: \(proc.terminationStatus)")
        }

        do {
            try process.run()
            self.process = process
            print("[Backend] Started on port \(port) (PID: \(process.processIdentifier))")

            // Wait a moment for server to be ready
            DispatchQueue.global().asyncAfter(deadline: .now() + 2.0) {
                if self.isRunning() {
                    print("[Backend] Server is ready")
                } else {
                    print("[Backend] Server may not have started correctly")
                }
            }
        } catch {
            print("[Backend] Failed to start: \(error)")
        }
    }

    /// Stop the backend server.
    func stop() {
        guard let process = process, process.isRunning else { return }
        process.terminate()
        self.process = nil
        print("[Backend] Stopped")
    }

    /// Check if the backend is responding.
    func isRunning() -> Bool {
        let semaphore = DispatchSemaphore(value: 0)
        var running = false

        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 2

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                running = true
            }
            semaphore.signal()
        }.resume()

        _ = semaphore.wait(timeout: .now() + 3)
        return running
    }

    /// Find the SUDOBRAIN project directory.
    private func findProjectDir() -> URL? {
        if let envPath = ProcessInfo.processInfo.environment["SUDOBRAIN_PROJECT_DIR"], !envPath.isEmpty {
            let envURL = URL(fileURLWithPath: NSString(string: envPath).expandingTildeInPath)
            if FileManager.default.fileExists(atPath: envURL.appendingPathComponent("backend/main.py").path) {
                return envURL
            }
        }

        let candidates = [
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Documents/SudoBrain"),
            URL(fileURLWithPath: FileManager.default.currentDirectoryPath),
        ]
        for candidate in candidates {
            if FileManager.default.fileExists(atPath: candidate.appendingPathComponent("backend/main.py").path) {
                return candidate
            }
        }
        return nil
    }
}
