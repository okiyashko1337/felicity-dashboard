import Foundation

actor FelicityAPI: DashboardProviding {
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func current(baseURL: URL, previous: DashboardSnapshot) async throws -> DashboardSnapshot {
        try DashboardSnapshot.applyingCurrent(await data(baseURL: baseURL, path: "/api/device/current"), to: previous)
    }

    func summary(baseURL: URL, previous: DashboardSnapshot) async throws -> DashboardSnapshot {
        try DashboardSnapshot.applyingSummary(await data(baseURL: baseURL, path: "/api/device/summary"), to: previous)
    }

    func status(baseURL: URL) async throws -> ServerStatus {
        let payload = try JSONSerialization.jsonObject(with: await data(baseURL: baseURL, path: "/api/status")) as? [String: Any]
        return ServerStatus(
            online: payload?["online"] as? Bool ?? true,
            version: payload?["app_version"] as? String ?? "—"
        )
    }

    private func data(baseURL: URL, path: String) async throws -> Data {
        let url = baseURL.appending(path: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 6
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw APIError.invalidResponse((response as? HTTPURLResponse)?.statusCode)
        }
        return data
    }
}

enum APIError: LocalizedError {
    case invalidServer
    case invalidResponse(Int?)

    var errorDescription: String? {
        switch self {
        case .invalidServer: return "Invalid Felicity server address"
        case let .invalidResponse(code): return code.map { "Felicity HTTP \($0)" } ?? "Invalid Felicity response"
        }
    }
}
