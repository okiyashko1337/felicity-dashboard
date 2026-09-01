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
}
