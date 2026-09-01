import Foundation

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published private(set) var snapshot = DashboardSnapshot()
    @Published private(set) var status = ServerStatus()
    @Published private(set) var error = "Waiting for data"
    @Published var serverText: String

    private let api: any DashboardProviding
    private let defaults: UserDefaults

    init(api: any DashboardProviding = FelicityAPI(), defaults: UserDefaults = .standard) {
        self.api = api
        self.defaults = defaults
        serverText = defaults.string(forKey: "felicity.server") ?? "http://homeassistant.local:8000"
    }

    var isLive: Bool {
        status.online && snapshot.updatedAt.map { Date().timeIntervalSince($0) < 12 } == true
    }

    func saveServer() {
        serverText = serverText.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        defaults.set(serverText, forKey: "felicity.server")
    }

    func run() async {
        var iteration = 0
        while !Task.isCancelled {
            await refresh(includeSummary: iteration % 5 == 0, includeStatus: iteration % 3 == 0)
            iteration += 1
            try? await Task.sleep(for: .seconds(2))
        }
    }

    private func refresh(includeSummary: Bool, includeStatus: Bool) async {
        guard let baseURL = URL(string: serverText), baseURL.scheme != nil else {
            status.online = false
            error = APIError.invalidServer.localizedDescription
            return
        }
        do {
            snapshot = try await api.current(baseURL: baseURL, previous: snapshot)
            if includeSummary { snapshot = try await api.summary(baseURL: baseURL, previous: snapshot) }
            if includeStatus { status = try await api.status(baseURL: baseURL) }
            else { status.online = true }
            error = ""
        } catch {
            status.online = false
            self.error = error.localizedDescription
        }
    }
}
