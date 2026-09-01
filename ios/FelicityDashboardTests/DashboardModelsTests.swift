import XCTest
@testable import FelicityDashboard

final class DashboardModelsTests: XCTestCase {
    func testCurrentPayloadMatchesAndroidSemantics() throws {
        let data = Data(#"{"parsed":{"pv_power_w":{"total":2730,"pv1":530,"pv2":2200},"load_power_w":{"total":4230,"l1":1110,"l2":880,"l3":2240},"soc_percent":78,"battery_voltage_v":52.6,"battery_power_w":-1680,"grid_voltage_v":{"l1":230.7,"l2":230.8,"l3":230.9},"grid_power_w":{"total":0},"grid_frequency_hz":50}}"#.utf8)
        let value = try DashboardSnapshot.applyingCurrent(data)
        XCTAssertEqual(value.solar, 2730)
        XCTAssertEqual(value.load3, 2240)
        XCTAssertEqual(value.batteryPower, -1680)
        XCTAssertEqual(value.gridVoltage, 230.8, accuracy: 0.001)
    }

    func testSummaryMergesWithoutDestroyingLiveValues() throws {
        let data = Data(#"{"system":{"cpu_percent":1,"memory_percent":29,"temperature_c":74,"disk_percent":22},"today":{"pv_kwh":60.8,"load_kwh":66.3,"coverage_percent":92}}"#.utf8)
        var original = DashboardSnapshot()
        original.solar = 2730
        let value = try DashboardSnapshot.applyingSummary(data, to: original)
        XCTAssertEqual(value.solar, 2730)
        XCTAssertEqual(value.todaySolar, 60.8)
        XCTAssertEqual(value.coverage, 92)
    }

    func testChartPayloadPreservesChannelsAndGaps() throws {
        let data = Data(#"{"channels":3,"samples":[[0,12,-4],null,[25,18,0]]}"#.utf8)
        let chart = try DashboardChart.decode(data)
        XCTAssertEqual(chart.channels, 3)
        XCTAssertEqual(chart.samples.count, 3)
        XCTAssertEqual(chart.samples[0], [0, 12, -4])
        XCTAssertNil(chart.samples[1])
        XCTAssertEqual(chart.samples[2], [25, 18, 0])
    }

    func testH264FragmentedKeyframeIsReassembled() {
        var units: [VideoAccessUnit] = []
        let depacketizer = RTPDepacketizer(isHEVC: false) { units.append($0) }
        depacketizer.accept(rtp(sequence: 1, timestamp: 90_000, marker: false, payload: [0x7c, 0x85, 1, 2]))
        depacketizer.accept(rtp(sequence: 2, timestamp: 90_000, marker: true, payload: [0x7c, 0x45, 3, 4]))
        XCTAssertEqual(units.count, 1)
        XCTAssertTrue(units[0].isKeyframe)
        XCTAssertEqual(units[0].annexB, Data([0, 0, 0, 1, 0x65, 1, 2, 3, 4]))
    }

    func testH265FragmentedKeyframeIsReassembled() {
        var units: [VideoAccessUnit] = []
        let depacketizer = RTPDepacketizer(isHEVC: true) { units.append($0) }
        depacketizer.accept(rtp(sequence: 8, timestamp: 180_000, marker: false, payload: [0x62, 0x01, 0x93, 7, 8]))
        depacketizer.accept(rtp(sequence: 9, timestamp: 180_000, marker: true, payload: [0x62, 0x01, 0x53, 9, 10]))
        XCTAssertEqual(units.count, 1)
        XCTAssertTrue(units[0].isKeyframe)
        XCTAssertEqual(units[0].annexB, Data([0, 0, 0, 1, 0x26, 0x01, 7, 8, 9, 10]))
    }

    func testSDPFindsFirstVideoSectionAndResolvesTrack() throws {
        let raw = """
        v=0\r
        o=- 0 0 IN IP4 127.0.0.1\r
        s=Ajax live\r
        t=0 0\r
        m=video 0 RTP/AVP 96\r
        a=rtpmap:96 H264/90000\r
        a=framesize:96 640-360\r
        a=fmtp:96 packetization-mode=1;sprop-parameter-sets=Z0IAH5WoFAFuQA==,aM48gA==\r
        a=control:trackID=0\r
        m=audio 0 RTP/AVP 9\r
        a=control:trackID=1\r
        """
        let parsed = try SDPDescription.parse(raw, contentBase: "rtsp://192.168.13.234:8554/camera", fallbackSize: (1920, 1080))
        XCTAssertEqual(parsed.trackURI, "rtsp://192.168.13.234:8554/camera/trackID=0")
        XCTAssertEqual(parsed.format.width, 640)
        XCTAssertEqual(parsed.format.height, 360)
        XCTAssertFalse(parsed.format.isHEVC)
        XCTAssertEqual(parsed.format.parameterSets.count, 2)
    }

    func testThreeEyePayloadKeepsOnlySupportedAIEvents() throws {
        let data = Data(#"{"objects":[{"track_id":42,"object_class":"person","captured_at_utc":"2026-08-30T07:43:26Z","first_seen_utc":"2026-08-30T07:43:20Z","last_seen_utc":"2026-08-30T07:43:31Z","camera_name":"Porch VF","confidence":0.93,"thumbnail_url":"/api/objects/42/thumbnail","image_url":"/api/objects/42/image"},{"track_id":43,"object_class":"motion","captured_at_utc":"2026-08-30T07:44:00Z","camera_name":"Porch VF"}]}"#.utf8)
        let events = try ThreeEyeAPI.parseEvents(data, baseURL: try XCTUnwrap(URL(string: "http://192.168.13.148:8765")))
        XCTAssertEqual(events.count, 1)
        XCTAssertEqual(events[0].trackID, 42)
        XCTAssertEqual(events[0].eventClass, .person)
        XCTAssertEqual(events[0].camera, "Porch VF")
        XCTAssertEqual(events[0].thumbnailURL?.absoluteString, "http://192.168.13.148:8765/api/objects/42/thumbnail")
    }

    func testAjaxActivityBatchDecodesAndBuildsContextInterval() throws {
        let startUS: UInt64 = 1_788_244_800_000_000
        let endUS = startUS + 4_000_000
        let started = protoMessage([
            protoVarint(1, startUS),
            protoBytes(3, protoMessage([protoBytes(5, protoMessage([protoVarint(1, 2)])), protoVarint(101, 0)])),
        ])
        let ended = protoMessage([
            protoVarint(1, endUS),
            protoBytes(3, protoMessage([protoBytes(5, protoMessage([protoVarint(1, 2)])), protoVarint(101, 1)])),
        ])
        let batch = protoMessage([protoBytes(1, Data("A".utf8)), protoBytes(2, started), protoBytes(2, ended)])
        let boundaries = AjaxActivityDecoder.decode(batch)
        let intervals = ArchiveTimelineRules.intervals(from: boundaries)
        XCTAssertEqual(boundaries.count, 2)
        XCTAssertEqual(intervals.count, 1)
        XCTAssertEqual(intervals[0].kind, .person)
        XCTAssertEqual(intervals[0].start.timeIntervalSince1970, Double(startUS) / 1_000_000 - 6, accuracy: 0.001)
        XCTAssertEqual(intervals[0].end.timeIntervalSince1970, Double(endUS) / 1_000_000 + 6, accuracy: 0.001)
    }

    func testReplayClockReadsAjaxNTPHeaderExtension() throws {
        let unix: UInt32 = 1_788_244_800
        let ntp = UInt64(unix) + 2_208_988_800
        var packet = Data([0x90, 0xe0, 0, 1, 0, 1, 0x5f, 0x90, 0, 0, 0, 1, 0xab, 0xac, 0, 3])
        packet.append(contentsOf: [UInt8(ntp >> 24), UInt8((ntp >> 16) & 0xff), UInt8((ntp >> 8) & 0xff), UInt8(ntp & 0xff)])
        packet.append(contentsOf: [0, 0, 0, 0, 0, 0, 0, 0])
        let decoded = try XCTUnwrap(ReplayClock.date(fromRTP: packet))
        XCTAssertEqual(decoded.timeIntervalSince1970, Double(unix), accuracy: 0.001)
    }

    func testReplayClockFallsBackToPlayRangeAndRTPInfo() throws {
        let anchor = try XCTUnwrap(ReplayClock.rangeStart("clock=20260901T120000Z-"))
        let timestamp = try XCTUnwrap(ReplayClock.rtpInfoTimestamp("url=rtsp://nvr/track;seq=18;rtptime=900000"))
        let frame = ReplayClock.date(rtpTimestamp: timestamp &+ 135_000, anchorTimestamp: timestamp, anchorDate: anchor)
        XCTAssertEqual(frame.timeIntervalSince(anchor), 1.5, accuracy: 0.001)
    }

    func testTimelineGapChoosesNearestAndTiePrefersEarlier() throws {
        let origin = Date(timeIntervalSince1970: 10_000)
        let intervals = [
            ArchiveInterval(kind: .person, start: origin, end: origin.addingTimeInterval(10)),
            ArchiveInterval(kind: .animal, start: origin.addingTimeInterval(30), end: origin.addingTimeInterval(40)),
        ]
        XCTAssertEqual(ArchiveTimelineRules.nearestRecordedTime(to: origin.addingTimeInterval(18), in: intervals), origin.addingTimeInterval(10))
        XCTAssertEqual(ArchiveTimelineRules.nearestRecordedTime(to: origin.addingTimeInterval(20), in: intervals), origin.addingTimeInterval(10))
        XCTAssertEqual(ArchiveTimelineRules.nearestRecordedTime(to: origin.addingTimeInterval(24), in: intervals), origin.addingTimeInterval(30))
    }

    func testRenderGenerationRejectsFramesFromPreviousSeek() {
        var gate = RenderGenerationGate()
        let first = gate.advance()
        XCTAssertTrue(gate.accepts(first))
        let second = gate.advance()
        XCTAssertFalse(gate.accepts(first))
        XCTAssertTrue(gate.accepts(second))
    }

    private func rtp(sequence: UInt16, timestamp: UInt32, marker: Bool, payload: [UInt8]) -> Data {
        var bytes: [UInt8] = [0x80, marker ? 0xe0 : 0x60]
        bytes += [UInt8(sequence >> 8), UInt8(sequence & 0xff)]
        bytes += [UInt8(timestamp >> 24), UInt8((timestamp >> 16) & 0xff), UInt8((timestamp >> 8) & 0xff), UInt8(timestamp & 0xff)]
        bytes += [0, 0, 0, 1]
        bytes += payload
        return Data(bytes)
    }


    private func protoMessage(_ fields: [Data]) -> Data { fields.reduce(into: Data()) { $0.append($1) } }
    private func protoVarint(_ field: Int, _ value: UInt64) -> Data {
        var output = varint(UInt64(field << 3))
        output.append(varint(value))
        return output
    }
    private func protoBytes(_ field: Int, _ value: Data) -> Data {
        var output = varint(UInt64(field << 3 | 2))
        output.append(varint(UInt64(value.count)))
        output.append(value)
        return output
    }
    private func varint(_ source: UInt64) -> Data {
        var value = source
        var output = Data()
        while value >= 0x80 { output.append(UInt8(value & 0x7f) | 0x80); value >>= 7 }
        output.append(UInt8(value))
        return output
    }
}
