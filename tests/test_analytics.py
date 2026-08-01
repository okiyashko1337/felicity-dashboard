from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analytics import (
    build_daily_aggregates,
    build_energy_analytics,
    build_gap_statistics,
    build_period_analytics,
)
from database import (
    ensure_energy_daily,
    get_energy_daily,
    get_telemetry_range,
    initialize_database,
    save_telemetry_snapshot,
)


def telemetry(
    pv: float,
    load: float,
    grid: float,
    battery: float,
    soc: float,
    device_timestamp: str | None = None,
) -> dict:
    result = {
        "pv_power_w": {"total": pv},
        "load_power_w": {"total": load},
        "grid_power_w": {"total": grid},
        "battery_power_w": battery,
        "battery_voltage_v": 53.2,
        "battery_current_a": battery / 53.2,
        "soc_percent": soc,
        "batteries": [
            {"current_a": battery / 106.4, "cell_delta_mv": 4},
            {"current_a": battery / 106.4, "cell_delta_mv": 5},
        ],
    }
    if device_timestamp:
        result["device"] = {"device_timestamp": device_timestamp}
    return result


class AnalyticsTests(unittest.TestCase):
    def test_integrates_energy_and_battery_directions(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        rows = [
            {"timestamp": start.isoformat(), "parsed": telemetry(4000, 2000, -500, 1500, 40)},
            {"timestamp": (start + timedelta(hours=1)).isoformat(), "parsed": telemetry(4000, 2000, -500, 1500, 60)},
        ]
        result = build_energy_analytics(rows, max_points=60, max_gap_seconds=7200)

        self.assertEqual(result["stats"]["pv_kwh"], 4.0)
        self.assertEqual(result["stats"]["load_kwh"], 2.0)
        self.assertEqual(result["stats"]["grid_export_kwh"], 0.5)
        self.assertEqual(result["stats"]["battery_charge_kwh"], 1.5)
        self.assertEqual(result["stats"]["self_consumption_kwh"], 3.5)
        self.assertEqual(result["stats"]["soc_min_percent"], 40)
        self.assertEqual(result["stats"]["soc_max_percent"], 60)

    def test_does_not_integrate_long_data_gaps(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        rows = [
            {"timestamp": start.isoformat(), "parsed": telemetry(5000, 1000, 0, 4000, 40)},
            {"timestamp": (start + timedelta(minutes=10)).isoformat(), "parsed": telemetry(5000, 1000, 0, 4000, 41)},
        ]
        result = build_energy_analytics(rows)
        self.assertEqual(result["stats"]["pv_kwh"], 0)
        self.assertEqual(result["integrated_seconds"], 0)

    def test_reports_internal_and_boundary_gaps(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        rows = [
            {"timestamp": (start + timedelta(seconds=second)).isoformat(), "parsed": telemetry(1, 1, 0, 0, 50)}
            for second in (0, 2, 12, 14)
        ]

        result = build_gap_statistics(
            rows,
            range_start=start,
            range_end=start + timedelta(seconds=20),
            max_gap_seconds=5,
            now=start + timedelta(seconds=20),
        )

        self.assertEqual(result["gap_count"], 2)
        self.assertEqual(result["longest_gap_seconds"], 10)
        self.assertEqual(result["coverage_percent"], 20.0)

    def test_period_analytics_marks_days_without_data(self) -> None:
        rows = [
            {
                "day": day,
                **{field: 1000 for field in ("pv_wh", "load_wh", "grid_import_wh", "grid_export_wh", "battery_charge_wh", "battery_discharge_wh")},
                "integrated_seconds": 86400,
                "sample_count": 10,
            }
            for day in ("2026-07-31", "2026-08-02")
        ]

        result = build_period_analytics(
            rows,
            start_day=datetime(2026, 7, 31).date(),
            end_day=datetime(2026, 8, 3).date(),
            now=datetime(2026, 8, 4, tzinfo=timezone.utc),
        )

        self.assertEqual([point["label"] for point in result["points"]], ["2026-07-31", "2026-08-01", "2026-08-02"])
        self.assertFalse(result["points"][1]["has_data"])
        self.assertEqual(result["gap_statistics"]["missing_day_count"], 1)
        self.assertEqual(result["gap_statistics"]["coverage_percent"], 66.7)

    def test_range_query_is_half_open(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            for hour in (0, 12, 24):
                save_telemetry_snapshot(
                    raw_data={},
                    parsed_data=telemetry(1, 1, 0, 0, 50),
                    source="test",
                    db_path=db_path,
                    timestamp=start + timedelta(hours=hour),
                )
            rows = get_telemetry_range(start, start + timedelta(days=1), db_path)
        self.assertEqual([row["id"] for row in rows], [1, 2])

    def test_daily_aggregates_use_device_day_and_skip_long_gaps(self) -> None:
        start = datetime(2026, 7, 30, 21, 59, 58, tzinfo=timezone.utc)
        rows = [
            {
                "timestamp": start.isoformat(),
                "parsed": telemetry(3600, 1800, 600, 900, 40, "2026-07-30T23:59:58"),
            },
            {
                "timestamp": (start + timedelta(seconds=2)).isoformat(),
                "parsed": telemetry(3600, 1800, 600, 900, 41, "2026-07-31T00:00:00"),
            },
            {
                "timestamp": (start + timedelta(seconds=4)).isoformat(),
                "parsed": telemetry(3600, 1800, 600, 900, 42, "2026-07-31T00:00:02"),
            },
            {
                "timestamp": (start + timedelta(minutes=10)).isoformat(),
                "parsed": telemetry(9000, 9000, 9000, 9000, 43, "2026-07-31T00:09:58"),
            },
        ]

        result = build_daily_aggregates(rows)

        self.assertEqual([row["day"] for row in result], ["2026-07-30", "2026-07-31"])
        self.assertEqual(result[0]["pv_wh"], 0)
        self.assertEqual(result[1]["pv_wh"], 2)
        self.assertEqual(result[1]["load_wh"], 1)
        self.assertEqual(result[1]["soc_min_percent"], 41)
        self.assertEqual(result[1]["soc_max_percent"], 43)

    def test_period_analytics_combines_days_and_months(self) -> None:
        rows = [
            {
                "day": "2026-07-31",
                "pv_wh": 5000,
                "load_wh": 3000,
                "grid_import_wh": 500,
                "grid_export_wh": 1000,
                "battery_charge_wh": 1200,
                "battery_discharge_wh": 700,
                "sample_count": 10,
                "soc_start_percent": 40,
                "soc_end_percent": 60,
                "soc_min_percent": 38,
                "soc_max_percent": 62,
            },
            {
                "day": "2026-08-01",
                "pv_wh": 7000,
                "load_wh": 4000,
                "grid_import_wh": 200,
                "grid_export_wh": 2000,
                "battery_charge_wh": 1800,
                "battery_discharge_wh": 500,
                "sample_count": 12,
                "soc_start_percent": 60,
                "soc_end_percent": 75,
                "soc_min_percent": 55,
                "soc_max_percent": 78,
            },
        ]

        result = build_period_analytics(rows, group_by_month=True)

        self.assertEqual([point["label"] for point in result["points"]], ["2026-07", "2026-08"])
        self.assertEqual(result["stats"]["pv_kwh"], 12)
        self.assertEqual(result["stats"]["self_consumption_kwh"], 9)
        self.assertEqual(result["stats"]["soc_min_percent"], 38)
        self.assertEqual(result["stats"]["soc_max_percent"], 78)

    def test_daily_backfill_is_idempotent(self) -> None:
        start = datetime(2026, 7, 31, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "felicity.db"
            initialize_database(db_path)
            for second in (0, 2, 4):
                save_telemetry_snapshot(
                    raw_data={},
                    parsed_data=telemetry(3600, 1800, 0, 0, 50),
                    source="test",
                    db_path=db_path,
                    timestamp=start + timedelta(seconds=second),
                )

            ensure_energy_daily(db_path)
            first = get_energy_daily(db_path=db_path)
            ensure_energy_daily(db_path)
            second = get_energy_daily(db_path=db_path)

        self.assertEqual(first, second)
        self.assertEqual(first[0]["pv_wh"], 4)
        self.assertEqual(first[0]["sample_count"], 3)


if __name__ == "__main__":
    unittest.main()
