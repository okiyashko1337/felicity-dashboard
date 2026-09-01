import Foundation

enum ArchivePlaybackState: Equatable, Sendable {
    case idle
    case connecting
    case seeking
    case paused
    case playing
    case failed(String)
}

actor ArchiveRTSPSession {
    typealias FormatHandler = @Sendable (VideoStreamFormat) -> Void
    typealias FrameHandler = @Sendable (VideoAccessUnit) -> Void
    typealias StatisticsHandler = @Sendable (LiveStreamStatistics) -> Void
    typealias StateHandler = @Sendable (ArchivePlaybackState) -> Void

    private let client = ArchiveRTSPClient()
    private var uri = ""
    private var username = ""
    private var password = ""
    private var challenge = ""
    private var sessionID = ""
    private var videoChannel = 0
    private var depacketizer: RTPDepacketizer?
    private var isHEVC = false
    private var keepAlive: Task<Void, Never>?
    private var generation = 0
    private var requestedTarget = Date.distantPast
    private var waitingForKeyframe = true
    private var pauseAfterFirstFrame = true
    private var acceptingFrames = false
    private var state: ArchivePlaybackState = .idle
    private var onFrame: FrameHandler?
    private var onStatistics: StatisticsHandler?
    private var onState: StateHandler?
    private var bytes = 0
    private var frames = 0
    private var lastBytes = 0
    private var lastFrames = 0
    private var measuredAt = ContinuousClock.now
    private var smoothedFPS: Double?
    private var smoothedKbps: Double?

    func open(
        descriptor: ProfileGReplayDescriptor,
        configuration: RecorderConfiguration,
        fallbackSize: (width: Int, height: Int),
        onFormat: @escaping FormatHandler,
        onFrame: @escaping FrameHandler,
        onStatistics: @escaping StatisticsHandler,
        onState: @escaping StateHandler
    ) async throws {
        await close()
        guard let url = URL(string: descriptor.uri), let host = url.host else { throw RTSPError.invalidURI }
        uri = descriptor.uri
        username = configuration.username
        password = configuration.password
        self.onFrame = onFrame
        self.onStatistics = onStatistics
        self.onState = onState
        setState(.connecting)
        try await client.connect(host: host, port: UInt16(url.port ?? 554)) { [weak self] channel, packet in
            Task { await self?.accept(channel: channel, packet: packet) }
        }
        let first = try await client.request("DESCRIBE", target: uri, headers: ["Accept: application/sdp"])
        challenge = first.headers["www-authenticate"] ?? ""
        let described: ArchiveRTSPResponse
        if first.code == 401 {
            guard !challenge.isEmpty else { throw RTSPError.authentication }
            described = try await authorized("DESCRIBE", target: uri, headers: ["Accept: application/sdp"])
        } else { described = first }
        guard described.code == 200 else { throw ArchiveError.response("Archive DESCRIBE \(described.code)") }
        let description = try SDPDescription.parse(described.body, contentBase: described.headers["content-base"] ?? uri, fallbackSize: fallbackSize)
        onFormat(description.format)
        isHEVC = description.format.isHEVC
        let setup = try await authorized(
            "SETUP", target: description.trackURI,
            headers: ["Transport: RTP/AVP/TCP;unicast;interleaved=0-1", "Require: onvif-replay"]
        )
        guard setup.code == 200 else { throw ArchiveError.response("Archive SETUP \(setup.code)") }
        sessionID = setup.headers["session"]?.components(separatedBy: ";").first?.trimmingCharacters(in: .whitespaces) ?? ""
        guard !sessionID.isEmpty else { throw ArchiveError.response("Archive RTSP session missing") }
        videoChannel = Self.interleavedChannel(setup.headers["transport"]) ?? 0
        setState(.paused)
        keepAlive = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(4))
                await self?.sendKeepAlive()
            }
        }
    }

    func seek(to target: Date, autoplay: Bool) async throws {
        guard !sessionID.isEmpty else { throw RTSPError.disconnected }
        generation += 1
        let seekGeneration = generation
        requestedTarget = target
        waitingForKeyframe = true
        pauseAfterFirstFrame = !autoplay
        acceptingFrames = false
        depacketizer = RTPDepacketizer(isHEVC: isHEVC) { [weak self] unit in
            Task { await self?.accept(unit, generation: seekGeneration) }
        }
        resetStatistics()
        setState(.seeking)
        _ = try? await authorized("PAUSE", target: uri, headers: ["Session: \(sessionID)", "Require: onvif-replay"])
        guard seekGeneration == generation else { return }
        let response = try await authorized(
            "PLAY", target: uri,
            headers: [
                "Session: \(sessionID)",
                "Require: onvif-replay",
                "Range: clock=\(ReplayClock.clock(target))-",
                "Rate-Control: yes",
                "Frames: all",
                "Immediate: yes",
                "Scale: 1.0",
            ]
        )
        guard response.code == 200 else { throw ArchiveError.response("Archive PLAY \(response.code)") }
        guard seekGeneration == generation else { return }
        acceptingFrames = true
    }

    func pause() async {
        guard !sessionID.isEmpty else { return }
        generation += 1
        acceptingFrames = false
        _ = try? await authorized("PAUSE", target: uri, headers: ["Session: \(sessionID)", "Require: onvif-replay"])
        setState(.paused)
        onStatistics?(.init(kbps: 0, fps: 0))
    }

    func close() async {
        keepAlive?.cancel()
        keepAlive = nil
        if !sessionID.isEmpty {
            _ = try? await authorized("TEARDOWN", target: uri, headers: ["Session: \(sessionID)"])
        }
        await client.close()
        depacketizer = nil
        sessionID = ""
        acceptingFrames = false
        setState(.idle)
    }

    private func accept(channel: Int, packet: Data) {
        guard channel == videoChannel, acceptingFrames else { return }
        bytes += packet.count
        if packet.count > 1, packet[packet.startIndex + 1] & 0x80 != 0 { frames += 1 }
        depacketizer?.accept(packet, archiveTime: ReplayClock.date(fromRTP: packet))
        publishStatisticsIfNeeded()
    }

    private func accept(_ unit: VideoAccessUnit, generation unitGeneration: Int) async {
        guard acceptingFrames, unitGeneration == generation else { return }
        if waitingForKeyframe {
            guard unit.isKeyframe else { return }
            if let time = unit.archiveTime, abs(time.timeIntervalSince(requestedTarget)) > 5 * 60 { return }
            waitingForKeyframe = false
        }
        onFrame?(unit)
        if pauseAfterFirstFrame {
            acceptingFrames = false
            _ = try? await authorized("PAUSE", target: uri, headers: ["Session: \(sessionID)", "Require: onvif-replay"])
            setState(.paused)
            onStatistics?(.init(kbps: 0, fps: 0))
        } else if state != .playing {
            setState(.playing)
        }
    }

    private func authorized(_ method: String, target: String, headers: [String]) async throws -> ArchiveRTSPResponse {
        var response = try await client.request(
            method, target: target, headers: headers,
            challenge: challenge, username: username, password: password
        )
        if response.code == 401, let fresh = response.headers["www-authenticate"], !fresh.isEmpty {
            challenge = fresh
            response = try await client.request(
                method, target: target, headers: headers,
                challenge: challenge, username: username, password: password
            )
        }
        return response
    }

    private func sendKeepAlive() async {
        guard !sessionID.isEmpty else { return }
        let response = try? await authorized("GET_PARAMETER", target: uri, headers: ["Session: \(sessionID)"])
        if response?.code != 200 { _ = try? await authorized("OPTIONS", target: uri, headers: ["Session: \(sessionID)"]) }
    }

    private func setState(_ value: ArchivePlaybackState) {
        state = value
        onState?(value)
    }

    private func resetStatistics() {
        bytes = 0; frames = 0; lastBytes = 0; lastFrames = 0
        smoothedFPS = nil; smoothedKbps = nil; measuredAt = .now
        onStatistics?(.init(kbps: 0, fps: 0))
    }

    private func publishStatisticsIfNeeded() {
        let elapsed = measuredAt.duration(to: .now)
        guard elapsed >= .seconds(1) else { return }
        let seconds = max(0.001, Double(elapsed.components.seconds) + Double(elapsed.components.attoseconds) / 1e18)
        let nextFPS = Double(frames - lastFrames) / seconds
        let nextKbps = Double(bytes - lastBytes) * 8 / seconds / 1000
        smoothedFPS = smoothedFPS.map { $0 * 0.9 + nextFPS * 0.1 } ?? nextFPS
        smoothedKbps = smoothedKbps.map { $0 * 0.8 + nextKbps * 0.2 } ?? nextKbps
        onStatistics?(.init(kbps: smoothedKbps ?? 0, fps: smoothedFPS ?? 0))
        lastBytes = bytes; lastFrames = frames; measuredAt = .now
    }

    private static func interleavedChannel(_ transport: String?) -> Int? {
        guard let transport, let range = transport.range(of: #"(?i)interleaved=(\d+)-"#, options: .regularExpression) else { return nil }
        let value = transport[range].split(separator: "=").last?.split(separator: "-").first
        return value.flatMap { Int($0) }
    }
}
