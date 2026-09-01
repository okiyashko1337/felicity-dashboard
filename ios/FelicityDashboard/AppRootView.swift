import SwiftUI

private enum FelicityPalette {
    static let background = Color(red: 7 / 255, green: 17 / 255, blue: 15 / 255)
    static let header = Color(red: 14 / 255, green: 48 / 255, blue: 43 / 255)
    static let card = Color(red: 13 / 255, green: 39 / 255, blue: 35 / 255)
    static let accent = Color(red: 89 / 255, green: 222 / 255, blue: 209 / 255)
    static let primary = Color(red: 232 / 255, green: 248 / 255, blue: 244 / 255)
    static let secondary = Color(red: 150 / 255, green: 190 / 255, blue: 184 / 255)
    static let live = Color(red: 98 / 255, green: 231 / 255, blue: 148 / 255)
    static let warning = Color(red: 1, green: 184 / 255, blue: 103 / 255)
}

struct AppRootView: View {
    @StateObject private var model = DashboardViewModel()
    @StateObject private var cameras = CameraRepository()
    @StateObject private var cameraPreferences = CameraPreferences()
    @State private var settingsPresented = false
    @State private var activeCamera: CameraDescriptor?

    var body: some View {
        NavigationStack {
            GeometryReader { proxy in
                let compact = proxy.size.width < 900
                VStack(spacing: 0) {
                    HeaderView(
                        model: model,
                        selectedCamera: cameras.selected,
                        compact: compact,
                        settingsPresented: $settingsPresented,
                        cameraAction: {
                            if let camera = cameras.selected { activeCamera = camera }
                            else { settingsPresented = true }
                        }
                    )
                    ScrollView {
                        DashboardGrid(snapshot: model.snapshot, compact: compact)
                            .padding(14)
                    }
                    .scrollBounceBehavior(.basedOnSize)
                }
                .background(FelicityPalette.background.ignoresSafeArea())
                .overlay {
                    if !model.isLive && model.snapshot.updatedAt == nil {
                        NoDataView(message: model.error)
                    }
                }
            }
        }
        .tint(FelicityPalette.accent)
        .task { await model.run() }
        .sheet(isPresented: $settingsPresented) {
            SettingsView(model: model, cameras: cameras, cameraPreferences: cameraPreferences)
                .presentationDetents([.large])
        }
        .fullScreenCover(item: $activeCamera) { camera in
            LiveCameraView(camera: camera, repository: cameras, preferences: cameraPreferences)
        }
    }
}

private struct HeaderView: View {
    @ObservedObject var model: DashboardViewModel
    let selectedCamera: CameraDescriptor?
    let compact: Bool
    @Binding var settingsPresented: Bool
    let cameraAction: () -> Void

    var body: some View {
        HStack(spacing: 16) {
            Button { settingsPresented = true } label: {
                Text("☯")
                    .font(.system(size: 38, weight: .semibold))
                    .foregroundStyle(FelicityPalette.accent)
                    .accessibilityLabel("Settings")
            }
            .buttonStyle(.plain)
            Text("v0.2.0 · iOS")
                .font(.headline.monospaced())
                .foregroundStyle(FelicityPalette.accent)
            Spacer()
            Button(action: cameraAction) {
                if compact {
                    Image(systemName: selectedCamera == nil ? "video.slash" : "video.fill")
                        .font(.headline)
                        .frame(width: 44, height: 42)
                } else {
                    Label(selectedCamera?.name ?? "SET UP CAMERAS", systemImage: selectedCamera == nil ? "video.slash" : "video.fill")
                        .font(.headline)
                        .lineLimit(1)
                        .padding(.horizontal, 14)
                        .frame(minHeight: 42)
                }
            }
            .buttonStyle(HomeHeaderButtonStyle())
            Text(model.isLive ? "LIVE" : "NO DATA")
                .font((compact ? Font.subheadline : Font.headline).bold())
                .foregroundStyle(model.isLive ? FelicityPalette.live : FelicityPalette.warning)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                Group {
                    if compact {
                        VStack(alignment: .trailing, spacing: 1) {
                            Text(context.date, format: .dateTime.day().month().year())
                            Text(context.date, format: .dateTime.hour().minute().second())
                        }
                    } else {
                        HStack(spacing: 18) {
                            Text(context.date, format: .dateTime.day().month().year())
                            Text(context.date, format: .dateTime.hour().minute().second())
                        }
                    }
                }
                .font((compact ? Font.subheadline : Font.title2).bold().monospacedDigit())
                .foregroundStyle(FelicityPalette.primary)
            }
        }
        .padding(.horizontal, compact ? 12 : 18)
        .frame(minHeight: 68)
        .background(FelicityPalette.header)
    }
}

private struct HomeHeaderButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .background(configuration.isPressed ? FelicityPalette.accent.opacity(0.35) : .black.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}

private struct DashboardGrid: View {
    let snapshot: DashboardSnapshot
    let compact: Bool

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12), count: compact ? 2 : 3)
    }

    var body: some View {
        LazyVGrid(columns: columns, spacing: 12) {
            MetricCard(title: "SOLAR", value: watts(snapshot.solar), detail: "PV1 \(number(snapshot.solar1, 0)) · PV2 \(number(snapshot.solar2, 0))")
            MetricCard(title: "HOME LOAD", value: watts(snapshot.load), detail: "\(number(snapshot.load1, 0)) · \(number(snapshot.load2, 0)) · \(number(snapshot.load3, 0))")
            MetricCard(title: "BATTERY", value: "\(number(snapshot.batteryPercent, 0))%", detail: "\(number(snapshot.batteryVoltage, 1)) V · \(signed(snapshot.batteryPower)) W")
            MetricCard(title: "GRID", value: "\(number(snapshot.gridVoltage, 1)) V", detail: "\(signed(snapshot.gridPower)) W · \(number(snapshot.gridFrequency, 1)) Hz")
            MetricCard(title: "SYSTEM", value: "\(number(snapshot.cpu, 0))%", detail: "RAM \(number(snapshot.memory, 0)) · TEMP \(number(snapshot.temperature, 0)) · DISK \(number(snapshot.disk, 0))")
            MetricCard(title: "TODAY", value: "\(number(snapshot.todaySolar, 2)) kWh", detail: "LOAD \(number(snapshot.todayLoad, 2)) · COVER \(number(snapshot.coverage, 0))%")
        }
    }

    private func watts(_ value: Double) -> String { "\(number(value, 0)) W" }
    private func signed(_ value: Double) -> String { "\(value > 0 ? "+" : value < 0 ? "−" : "")\(number(abs(value), 0))" }
    private func number(_ value: Double, _ decimals: Int) -> String {
        value.formatted(.number.precision(.fractionLength(decimals)).grouping(.automatic))
    }
}

private struct MetricCard: View {
    let title: String
    let value: String
    let detail: String

    var body: some View {
        Button(action: {}) {
            VStack(spacing: 12) {
                Text(title)
                    .font(.headline.bold())
                    .foregroundStyle(FelicityPalette.accent)
                Spacer(minLength: 4)
                Text(value)
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .minimumScaleFactor(0.55)
                    .foregroundStyle(FelicityPalette.primary)
                Spacer(minLength: 4)
                Text(detail)
                    .font(.title3)
                    .minimumScaleFactor(0.55)
                    .lineLimit(1)
                    .foregroundStyle(FelicityPalette.secondary)
            }
            .padding(18)
            .frame(maxWidth: .infinity, minHeight: 154)
            .background(
                LinearGradient(colors: [FelicityPalette.card, FelicityPalette.background.opacity(0.82)], startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 18)
            )
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(FelicityPalette.accent.opacity(0.48), lineWidth: 1.5))
        }
        .buttonStyle(.plain)
    }
}

private struct NoDataView: View {
    let message: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: "network.slash")
                .font(.system(size: 38, weight: .medium))
            Text("NO DATA")
                .font(.title.bold())
            Text(message)
                .font(.body)
                .multilineTextAlignment(.center)
                .foregroundStyle(FelicityPalette.primary.opacity(0.78))
        }
        .foregroundStyle(FelicityPalette.warning)
        .padding(.horizontal, 34)
        .padding(.vertical, 26)
        .background(.black.opacity(0.92), in: RoundedRectangle(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).stroke(FelicityPalette.warning.opacity(0.45)))
        .shadow(color: .black.opacity(0.55), radius: 24)
        .padding(30)
    }
}

private struct SettingsView: View {
    @ObservedObject var model: DashboardViewModel
    @ObservedObject var cameras: CameraRepository
    @ObservedObject var cameraPreferences: CameraPreferences
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Felicity server") {
                    TextField("http://homeassistant.local:8000", text: $model.serverText)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                Section("Ajax recorder · ONVIF") {
                    TextField("192.168.13.234:8080", text: $cameraPreferences.recorderHost)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("ONVIF username", text: $cameraPreferences.recorderUsername)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("ONVIF password", text: $cameraPreferences.recorderPassword)
                    Button {
                        cameraPreferences.save()
                        Task { await cameras.discover(using: cameraPreferences.recorderConfiguration) }
                    } label: {
                        HStack {
                            Label(cameras.cameras.isEmpty ? "Discover cameras" : "Refresh camera catalogue", systemImage: "arrow.triangle.2.circlepath.camera")
                            Spacer()
                            if cameras.isDiscovering { ProgressView() }
                        }
                    }
                    .disabled(cameras.isDiscovering)
                    if !cameras.error.isEmpty {
                        Text(cameras.error)
                            .foregroundStyle(.orange)
                    } else if !cameras.cameras.isEmpty {
                        LabeledContent("Cameras", value: cameras.cameras.count.formatted())
                    }
                }
                Section("3ye events") {
                    TextField("http://192.168.13.148:8765", text: $cameraPreferences.threeEyeURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    TextField("3ye username", text: $cameraPreferences.threeEyeUsername)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("3ye password", text: $cameraPreferences.threeEyePassword)
                    Text("Saved now for the next Events milestone. This build does not send push notifications.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                Section {
                    LabeledContent("Client", value: "iOS 0.2.0")
                    LabeledContent("Server", value: model.status.version)
                    LabeledContent("Connection", value: model.isLive ? "Live" : "Offline")
                    if !cameraPreferences.saveError.isEmpty {
                        LabeledContent("Keychain", value: cameraPreferences.saveError)
                    }
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        model.saveServer()
                        cameraPreferences.save()
                        dismiss()
                    }
                }
            }
        }
    }
}
