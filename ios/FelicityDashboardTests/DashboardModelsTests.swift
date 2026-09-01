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

    private func rtp(sequence: UInt16, timestamp: UInt32, marker: Bool, payload: [UInt8]) -> Data {
        var bytes: [UInt8] = [0x80, marker ? 0xe0 : 0x60]
        bytes += [UInt8(sequence >> 8), UInt8(sequence & 0xff)]
        bytes += [UInt8(timestamp >> 24), UInt8((timestamp >> 16) & 0xff), UInt8((timestamp >> 8) & 0xff), UInt8(timestamp & 0xff)]
        bytes += [0, 0, 0, 1]
        bytes += payload
        return Data(bytes)
    }
}
