import Foundation
import os

/// Shared client for communicating with the Python backend on localhost:8420.
class APIClient {
    static let shared = APIClient()
    private let baseURL = "http://127.0.0.1:8420"

    private init() {}

    /// Build a URLRequest with auth header and timeout.
    private func makeRequest(_ path: String, method: String = "GET", timeout: TimeInterval = 30) -> URLRequest? {
        guard let url = URL(string: "\(baseURL)\(path)") else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout

        // Add auth token if configured
        if let token = ProcessInfo.processInfo.environment["SUDOBRAIN_API_TOKEN"], !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        return request
    }

    func get<T: Decodable>(_ path: String, as type: T.Type) async throws -> T {
        guard let request = makeRequest(path) else {
            throw APIError.invalidURL
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response)
        return try JSONDecoder().decode(T.self, from: data)
    }

    func getRaw(_ path: String) async throws -> [[String: Any]] {
        guard let request = makeRequest(path) else {
            throw APIError.invalidURL
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response)
        guard let result = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else {
            throw APIError.decodingFailed
        }
        return result
    }

    func getRawObject(_ path: String) async throws -> [String: Any] {
        guard let request = makeRequest(path) else {
            throw APIError.invalidURL
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response)
        guard let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError.decodingFailed
        }
        return result
    }

    func post(_ path: String, body: [String: Any], timeout: TimeInterval = 120) async throws -> [String: Any] {
        guard var request = makeRequest(path, method: "POST", timeout: timeout) else {
            throw APIError.invalidURL
        }
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateResponse(response)
        guard let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError.decodingFailed
        }
        return result
    }

    func post(_ path: String, timeout: TimeInterval = 120) async throws -> [String: Any] {
        try await post(path, body: [:], timeout: timeout)
    }

    /// Check if the backend is reachable.
    func isReachable() async -> Bool {
        guard let request = makeRequest("/health", timeout: 3) else { return false }
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func validateResponse(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }
        switch httpResponse.statusCode {
        case 200..<300:
            return
        case 401:
            throw APIError.unauthorized
        case 404:
            throw APIError.notFound
        case 500..<600:
            throw APIError.serverError(httpResponse.statusCode)
        default:
            throw APIError.unexpectedStatus(httpResponse.statusCode)
        }
    }

    enum APIError: LocalizedError {
        case invalidURL
        case invalidResponse
        case decodingFailed
        case unauthorized
        case notFound
        case serverError(Int)
        case unexpectedStatus(Int)

        var errorDescription: String? {
            switch self {
            case .invalidURL: return "Invalid API URL"
            case .invalidResponse: return "Invalid response from server"
            case .decodingFailed: return "Failed to decode server response"
            case .unauthorized: return "Authentication failed"
            case .notFound: return "Resource not found"
            case .serverError(let code): return "Server error (\(code))"
            case .unexpectedStatus(let code): return "Unexpected response (\(code))"
            }
        }
    }
}
