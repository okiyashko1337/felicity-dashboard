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
    @State private var settingsPresented = false

    var body: some View {
        NavigationStack {
            GeometryReader { proxy in
                let compact = proxy.size.width < 900
                VStack(spacing: 0) {
                    HeaderView(model: model, compact: compact, settingsPresented: $settingsPresented)
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
            SettingsView(model: model)
                .presentationDetents([.medium])
        }
    }
}

private struct HeaderView: View {
    @ObservedObject var model: DashboardViewModel
    let compact: Bool
    @Binding var settingsPresented: Bool

    var body: some View {
        HStack(spacing: 16) {
            Button { settingsPresented = true } label: {
                Text("☯")
                    .font(.system(size: 38, weight: .semibold))
                    .foregroundStyle(FelicityPalette.accent)
                    .accessibilityLabel("Settings")
            }
            .buttonStyle(.plain)
            Text("v0.1.0 · iOS")
                .font(.headline.monospaced())
                .foregroundStyle(FelicityPalette.accent)
            Spacer()
            if !compact {
                Button(action: {}) {
                    Label("CAMERAS", systemImage: "video.fill")
                        .font(.headline)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(.black.opacity(0.35), in: RoundedRectangle(cornerRadius: 12))
                }
                .disabled(true)
            }
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
                Section {
                    LabeledContent("Client", value: "iOS 0.1.0")
                    LabeledContent("Server", value: model.status.version)
                    LabeledContent("Connection", value: model.isLive ? "Live" : "Offline")
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        model.saveServer()
                        dismiss()
                    }
                }
            }
        }
    }
}
