import AudioToolbox
import OSLog
import SwiftUI
import UIKit

@MainActor
final class ArchiveViewModel: ObservableObject {
    @Published private(set) var camera: CameraDescriptor
    @Published private(set) var quality: StreamQuality
    @Published private(set) var state: ArchivePlaybackState = .idle
    @Published private(set) var statistics = LiveStreamStatistics(kbps: 0, fps: 0)
    @Published private(set) var format: VideoStreamFormat?
    @Published private(set) var currentTime: Date?
    @Published private(set) var intervals: [ArchiveInterval] = []
    @Published private(set) var poster: UIImage?
    @Published private(set) var error = ""
    @Published private(set) var visibleStart = Calendar.current.startOfDay(for: .now)
    @Published private(set) var visibleSpan: TimeInterval = 24 * 60 * 60
    @Published private(set) var isLoadingTimeline = false

    let renderer = SampleBufferRenderer()

    private let repository: CameraRepository
    private let preferences: CameraPreferences
    private let threeEye: ThreeEyeConfiguration?
    private var entryEvent: ThreeEyeEvent?
    private let session = ArchiveRTSPSession()
    private let activityClient = AjaxActivityClient()
    private var seekTask: Task<Void, Never>?
    private var timelineTask: Task<Void, Never>?
    private var started = false
    private var seekRequestedAt: Date?
    private let logger = Logger(subsystem: "io.github.homedashboard.ios", category: "Archive")

    init(
        camera: CameraDescriptor,
        event: ThreeEyeEvent?,
        repository: CameraRepository,
        preferences: CameraPreferences
    ) {
        self.camera = camera
        self.entryEvent = event
        self.repository = repository
        self.preferences = preferences
        self.threeEye = preferences.threeEyeConfiguration
        quality = repository.preferredQuality(for: camera, compactDisplay: UIScreen.main.bounds.width < 700)
    }

    var isPlaying: Bool { state == .playing }
    var stateLabel: String {
        switch state {
        case .idle: return "ARCHIVE"
        case .connecting: return "CONNECTING…"
        case .seeking: return "SEEKING…"
        case .paused: return "PAUSED"
        case .playing: return "PLAYBACK"
        case .failed: return "ARCHIVE ERROR"
        }
    }

    func start() async {
        guard !started else { return }
        started = true
        let target = await initialTarget()
        currentTime = target
        ArchiveMarkerStore.shared.set(target)
        await loadPoster()
        await openSession(at: target)
    }

    func stop() async {
        started = false
        seekTask?.cancel()
        timelineTask?.cancel()
        if let jpeg = renderer.snapshotJPEG() { await CameraPreviewStore.shared.save(jpeg, for: camera) }
        await session.close()
    }

    func togglePlayback() {
        playClick()
        if isPlaying {
            Task { await session.pause() }
        } else if let currentTime {
            seek(to: currentTime, autoplay: true, snapToRecording: false)
        }
    }

    func seek(to requested: Date, autoplay: Bool = false, snapToRecording: Bool = true) {
        playClick()
        let target = snapToRecording ? ArchiveTimelineRules.nearestRecordedTime(to: requested, in: intervals) ?? requested : requested
        seekTask?.cancel()
        renderer.beginSeek()
        state = .seeking
        seekRequestedAt = .now
        logger.info("Seek requested camera=\(self.camera.name, privacy: .public) target=\(target.timeIntervalSince1970, privacy: .public) autoplay=\(autoplay, privacy: .public)")
        seekTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(45))
            guard !Task.isCancelled, let self else { return }
            do { try await self.session.seek(to: target, autoplay: autoplay) }
            catch { await MainActor.run { self.error = error.localizedDescription; self.state = .failed(error.localizedDescription) } }
        }
    }

    func jumpRecording(_ direction: Int) {
        guard !intervals.isEmpty else { return }
        let time = currentTime ?? intervals[0].start
        let target: Date?
        if direction < 0 {
            target = intervals.last(where: { $0.end < time.addingTimeInterval(-0.25) })?.start ?? intervals.first?.start
        } else {
            target = intervals.first(where: { $0.start > time.addingTimeInterval(0.25) })?.start ?? intervals.last?.start
        }
        if let target { seek(to: target, snapToRecording: false) }
    }

    func toggleQuality() async {
        let target = currentTime ?? .now
        if let jpeg = renderer.snapshotJPEG() {
            poster = UIImage(data: jpeg)
            await CameraPreviewStore.shared.save(jpeg, for: camera)
        }
        await session.close()
        quality = quality == .lq ? .hq : .lq
        repository.setPreferredQuality(quality, for: camera)
        format = nil
        statistics = .init(kbps: 0, fps: 0)
        renderer.flush()
        await openSession(at: target)
    }

    func switchCamera(to camera: CameraDescriptor) async {
        guard camera.id != self.camera.id else { return }
        let target = currentTime ?? ArchiveMarkerStore.shared.value() ?? .now
        if let jpeg = renderer.snapshotJPEG() { await CameraPreviewStore.shared.save(jpeg, for: self.camera) }
        await session.close()
        self.camera = camera
        repository.select(camera)
        quality = repository.preferredQuality(for: camera, compactDisplay: UIScreen.main.bounds.width < 700)
        entryEvent = nil
        format = nil
        intervals = []
        poster = nil
        renderer.flush()
        if let cached = await CameraPreviewStore.shared.data(for: camera) { poster = UIImage(data: cached) }
        await openSession(at: target)
    }

    func chooseDay(_ date: Date) {
        let calendar = Calendar.current
        let existing = currentTime ?? date
        let components = calendar.dateComponents([.hour, .minute, .second], from: existing)
        var target = calendar.startOfDay(for: date)
        target = calendar.date(byAdding: components, to: target) ?? target
        loadTimeline(around: target)
    }

    func panTimeline(seconds: TimeInterval) {
        let dayStart = Calendar.current.startOfDay(for: currentTime ?? visibleStart)
        let dayEnd = dayStart.addingTimeInterval(24 * 60 * 60)
        visibleStart = min(max(dayStart, visibleStart.addingTimeInterval(seconds)), dayEnd.addingTimeInterval(-visibleSpan))
    }

    private func initialTarget() async -> Date {
        if let captured = entryEvent?.capturedAt { return captured }
        if let marker = ArchiveMarkerStore.shared.value() { return marker }
        if let threeEye {
            let events = try? await ThreeEyeAPI().events(configuration: threeEye, camera: camera.name, classes: Set(ThreeEyeEventClass.allCases), limit: 8)
            if let captured = events?.first?.capturedAt { return captured }
        }
        return Date().addingTimeInterval(-5)
    }

    private func loadPoster() async {
        if let event = entryEvent, let url = event.imageURL ?? event.thumbnailURL, let threeEye,
           let data = try? await ThreeEyeImageStore.shared.data(for: url, configuration: threeEye), let image = UIImage(data: data) {
            poster = image
            return
        }
        if let data = await CameraPreviewStore.shared.data(for: camera) { poster = UIImage(data: data) }
    }

    private func openSession(at target: Date) async {
        error = ""
        loadTimeline(around: target)
        do {
            let descriptor = try await ProfileGArchiveService.shared.replay(camera: camera, quality: quality, configuration: preferences.recorderConfiguration)
            try await session.open(
                descriptor: descriptor,
                configuration: preferences.recorderConfiguration,
                fallbackSize: camera.encodedSize(for: quality),
                onFormat: { [weak self] value in
                    Task { @MainActor in self?.format = value; self?.renderer.configure(value) }
                },
                onFrame: { [weak self] unit in
                    Task { @MainActor in
                        guard let self else { return }
                        self.renderer.enqueue(unit)
                        guard let time = unit.archiveTime else { return }
                        for _ in 0..<8 where !self.renderer.isReady { try? await Task.sleep(for: .milliseconds(16)) }
                        guard self.renderer.isReady else { return }
                        self.acceptDecodedTime(time)
                        if let began = self.seekRequestedAt {
                            self.logger.info("First decoded archive frame camera=\(self.camera.name, privacy: .public) actual=\(time.timeIntervalSince1970, privacy: .public) latency_ms=\(Int(Date().timeIntervalSince(began) * 1000), privacy: .public)")
                            self.seekRequestedAt = nil
                        }
                    }
                },
                onStatistics: { [weak self] value in Task { @MainActor in self?.statistics = value } },
                onState: { [weak self] value in Task { @MainActor in self?.state = value } }
            )
            seek(to: target, autoplay: false, snapToRecording: false)
        } catch {
            self.error = error.localizedDescription
            state = .failed(error.localizedDescription)
        }
    }

    private func loadTimeline(around target: Date) {
        timelineTask?.cancel()
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: target)
        let end = calendar.date(byAdding: .day, value: 1, to: start) ?? start.addingTimeInterval(24 * 60 * 60)
        isLoadingTimeline = true
        timelineTask = Task { [weak self] in
            guard let self else { return }
            do {
                let loaded = try await self.activityClient.fetch(
                    camera: self.camera,
                    quality: self.quality,
                    configuration: self.preferences.recorderConfiguration,
                    start: start,
                    end: end
                )
                guard !Task.isCancelled else { return }
                var combined = loaded
                if let threeEye = self.threeEye,
                   let faces = try? await ThreeEyeAPI().events(configuration: threeEye, camera: self.camera.name, classes: [.face], limit: 200) {
                    combined.append(contentsOf: faces.compactMap { event in
                        guard let time = event.capturedAt else { return nil }
                        return ArchiveInterval(kind: .face, start: time.addingTimeInterval(-ArchiveTimelineRules.context), end: time.addingTimeInterval(ArchiveTimelineRules.context))
                    })
                    combined.sort { $0.start < $1.start }
                }
                self.intervals = combined
                self.visibleSpan = ArchiveTimelineRules.adaptiveSpan(eventCount: combined.count)
                self.centerTimeline(on: target, dayStart: start, dayEnd: end)
                self.isLoadingTimeline = false
            } catch {
                guard !Task.isCancelled else { return }
                self.isLoadingTimeline = false
                if self.error.isEmpty { self.error = error.localizedDescription }
                self.visibleSpan = 24 * 60 * 60
                self.visibleStart = start
            }
        }
    }

    private func centerTimeline(on target: Date, dayStart: Date, dayEnd: Date) {
        let proposed = target.addingTimeInterval(-visibleSpan / 2)
        visibleStart = min(max(dayStart, proposed), dayEnd.addingTimeInterval(-visibleSpan))
    }

    private func acceptDecodedTime(_ time: Date) {
        let calendar = Calendar.current
        if state == .playing, let currentTime, time < currentTime { return }
        let previousDay = currentTime.map(calendar.startOfDay(for:))
        currentTime = time
        ArchiveMarkerStore.shared.set(time)
        let dayStart = calendar.startOfDay(for: time)
        if previousDay != nil, previousDay != dayStart {
            loadTimeline(around: time)
        } else if time < visibleStart || time > visibleStart.addingTimeInterval(visibleSpan) {
            let dayEnd = calendar.date(byAdding: .day, value: 1, to: dayStart) ?? dayStart.addingTimeInterval(24 * 60 * 60)
            centerTimeline(on: time, dayStart: dayStart, dayEnd: dayEnd)
        }
    }

    private func playClick() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        AudioServicesPlaySystemSound(1104)
    }
}

struct ArchiveView: View {
    @ObservedObject var repository: CameraRepository
    @ObservedObject var preferences: CameraPreferences
    let backLabel: String
    @StateObject private var model: ArchiveViewModel
    @State private var cameraPicker = false
    @State private var livePresented = false
    @State private var calendarPresented = false
    @Environment(\.dismiss) private var dismiss

    init(camera: CameraDescriptor, event: ThreeEyeEvent?, backLabel: String, repository: CameraRepository, preferences: CameraPreferences) {
        self.repository = repository
        self.preferences = preferences
        self.backLabel = backLabel
        _model = StateObject(wrappedValue: ArchiveViewModel(camera: camera, event: event, repository: repository, preferences: preferences))
    }

    var body: some View {
        VStack(spacing: 0) {
            archiveHeader
            ZStack(alignment: .bottomLeading) {
                ArchiveVideoCanvas(renderer: model.renderer, camera: model.camera, poster: model.poster)
                if case .failed = model.state {
                    Text(model.error)
                        .font(.headline)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.orange)
                        .padding(24)
                        .background(.black.opacity(0.84), in: RoundedRectangle(cornerRadius: 16))
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                controls
            }
            ArchiveTimelineView(model: model)
                .frame(height: 112)
        }
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .task { await model.start() }
        .onDisappear { Task { await model.stop() } }
        .fullScreenCover(isPresented: $cameraPicker) {
            CameraWallView(repository: repository, backLabel: "ARCHIVE") { camera in Task { await model.switchCamera(to: camera) } }
        }
        .fullScreenCover(isPresented: $livePresented) {
            LiveCameraView(camera: model.camera, repository: repository, preferences: preferences)
        }
        .sheet(isPresented: $calendarPresented) {
            VStack(spacing: 18) {
                Text("RECORDING DATE").font(.headline.bold())
                DatePicker("Date", selection: Binding(get: { model.currentTime ?? .now }, set: { model.chooseDay($0); calendarPresented = false }), displayedComponents: .date)
                    .datePickerStyle(.graphical)
            }
            .padding(24)
            .presentationDetents([.medium, .large])
        }
    }

    private var archiveHeader: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { headerContents }
            HStack(spacing: 6) { headerContentsCompact }
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 66)
        .foregroundStyle(.white)
        .background(Color(red: 14 / 255, green: 48 / 255, blue: 43 / 255))
    }

    @ViewBuilder private var headerContents: some View {
        CameraBarButton(title: backLabel, systemImage: "chevron.left") { dismiss() }
        CameraBarButton(title: model.camera.name, systemImage: "video.fill") { cameraPicker = true }
        streamStatistics
        Spacer(minLength: 4)
        playbackClock
        Button(model.quality.rawValue) { Task { await model.toggleQuality() } }.buttonStyle(HeaderButtonStyle())
        CameraBarButton(title: "LIVE", systemImage: "dot.radiowaves.left.and.right") { livePresented = true }
    }

    @ViewBuilder private var headerContentsCompact: some View {
        CameraBarButton(title: backLabel, systemImage: "chevron.left") { dismiss() }
        CameraBarButton(title: model.camera.name, systemImage: "video.fill") { cameraPicker = true }
        Spacer(minLength: 0)
        playbackClock
        Button(model.quality.rawValue) { Task { await model.toggleQuality() } }.buttonStyle(HeaderButtonStyle())
    }

    private var streamStatistics: some View {
        VStack(spacing: 1) {
            Text(model.state == .paused ? "PAUSED" : "\(Int(model.statistics.kbps.rounded())) kbps · \(model.statistics.fps, specifier: "%.1f") FPS")
            Text("\(model.format?.width ?? model.camera.encodedSize(for: model.quality).width)×\(model.format?.height ?? model.camera.encodedSize(for: model.quality).height) · \(model.format?.codecName ?? "—")")
        }
        .font(.caption.bold().monospacedDigit())
    }

    private var playbackClock: some View {
        VStack(spacing: 1) {
            Text(model.stateLabel).font(.caption2.bold())
            Text(model.currentTime?.formatted(date: .omitted, time: .standard) ?? "--:--:--")
                .font(.title3.bold().monospacedDigit())
        }
        .fixedSize()
    }

    private var controls: some View {
        HStack(spacing: 10) {
            Button { model.togglePlayback() } label: { Image(systemName: model.isPlaying ? "pause.fill" : "play.fill") }
                .accessibilityLabel(model.isPlaying ? "Pause" : "Play")
            Button { model.jumpRecording(-1) } label: { Label("PREV", systemImage: "backward.end.fill") }
            Button { model.jumpRecording(1) } label: { Label("NEXT", systemImage: "forward.end.fill") }
            Button { calendarPresented = true } label: { Label("DATE", systemImage: "calendar") }
        }
        .font(.headline.bold())
        .buttonStyle(ArchiveControlButtonStyle())
        .padding(14)
    }
}

private struct ArchiveVideoCanvas: View {
    @ObservedObject var renderer: SampleBufferRenderer
    let camera: CameraDescriptor
    let poster: UIImage?

    var body: some View {
        ZStack {
            Color.black
            ZoomableVideoView(renderer: renderer, aspect: camera.displayAspect, rotationDegrees: camera.rotationDegrees)
            if let poster {
                Image(uiImage: poster)
                    .resizable()
                    .scaledToFit()
                    .opacity(renderer.isReady ? 0 : 1)
                    .allowsHitTesting(false)
            }
        }
        .animation(.easeOut(duration: 0.12), value: renderer.isReady)
    }
}

private struct ArchiveTimelineView: View {
    @ObservedObject var model: ArchiveViewModel

    var body: some View {
        GeometryReader { proxy in
            let width = max(1, proxy.size.width)
            ZStack(alignment: .leading) {
                Color(red: 0.07, green: 0.09, blue: 0.09)
                tickMarks(width: width)
                ForEach(model.intervals) { interval in
                    let x1 = x(interval.start, width: width)
                    let x2 = x(interval.end, width: width)
                    if x2 >= 0, x1 <= width {
                        RoundedRectangle(cornerRadius: 1.5)
                            .fill(interval.kind.color)
                            .frame(width: max(3, x2 - x1), height: 34)
                            .offset(x: x1, y: -18)
                    }
                }
                if let current = model.currentTime {
                    Rectangle().fill(.white).frame(width: 2, height: 92).offset(x: x(current, width: width))
                }
                if model.isLoadingTimeline { ProgressView().tint(.cyan).frame(maxWidth: .infinity) }
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onEnded { value in
                        if abs(value.translation.width) > 10 {
                            model.panTimeline(seconds: -Double(value.translation.width / width) * model.visibleSpan)
                        } else {
                            let ratio = min(1, max(0, value.location.x / width))
                            model.seek(to: model.visibleStart.addingTimeInterval(Double(ratio) * model.visibleSpan))
                        }
                    }
            )
        }
    }

    @ViewBuilder private func tickMarks(width: CGFloat) -> some View {
        let count = model.visibleSpan <= 3 * 3600 ? 7 : model.visibleSpan <= 6 * 3600 ? 7 : 9
        ForEach(0..<count, id: \.self) { index in
            let ratio = CGFloat(index) / CGFloat(max(1, count - 1))
            let date = model.visibleStart.addingTimeInterval(Double(ratio) * model.visibleSpan)
            VStack(spacing: 4) {
                Rectangle().fill(Color.white.opacity(0.55)).frame(width: 1, height: index % 2 == 0 ? 18 : 10)
                Text(date, format: .dateTime.hour().minute())
                    .font(.caption2.bold().monospacedDigit())
                    .foregroundStyle(.white.opacity(0.75))
            }
            .position(x: width * ratio, y: 86)
        }
    }

    private func x(_ date: Date, width: CGFloat) -> CGFloat {
        CGFloat(date.timeIntervalSince(model.visibleStart) / model.visibleSpan) * width
    }
}

private struct ArchiveControlButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .padding(.horizontal, 16)
            .frame(minHeight: 52)
            .background(configuration.isPressed ? Color.cyan.opacity(0.42) : Color(red: 0.18, green: 0.21, blue: 0.20).opacity(0.96), in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.white.opacity(0.2), lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
