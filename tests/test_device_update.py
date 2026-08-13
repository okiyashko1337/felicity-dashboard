from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from device_update import DeviceUpdateStore


class DeviceUpdateTests(unittest.TestCase):
    def make_store(self, root: Path) -> DeviceUpdateStore:
        firmware = root / "firmware"
        firmware.mkdir()
        (firmware / "felicity-esp32.bin").write_bytes(b"esp32 image")
        (firmware / "felicity-nextion.tft").write_bytes(b"nextion image")
        return DeviceUpdateStore(firmware, root / "state.json", "0.14.0")

    def test_request_and_matching_report_complete_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            requested = store.request("esp32")
            request = requested["request"]
            self.assertEqual(request["target"], "esp32")
            completed = store.report({
                "request_id": request["id"],
                "target": "esp32",
                "state": "complete",
                "progress_percent": 100,
                "device_version": "0.14.0",
            })
            self.assertIsNone(completed["request"])
            self.assertEqual(completed["status"]["state"], "complete")

    def test_mismatched_report_cannot_finish_an_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            request = store.request("nextion")["request"]
            with self.assertRaisesRegex(RuntimeError, "target"):
                store.report({
                    "request_id": request["id"],
                    "target": "esp32",
                    "state": "complete",
                })
            self.assertEqual(store.snapshot()["request"]["target"], "nextion")

    def test_parallel_request_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            store.request("esp32")
            with self.assertRaisesRegex(RuntimeError, "already active"):
                store.request("nextion")

    def test_manifest_contains_hash_size_and_relative_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            firmware = store.snapshot()["firmware"]["esp32"]
            self.assertEqual(len(firmware["sha256"]), 64)
            self.assertEqual(firmware["size"], len(b"esp32 image"))
            self.assertEqual(firmware["download_url"], "/api/device/firmware/esp32.bin")
            self.assertNotIn("path", firmware)

    def test_new_esp32_image_confirms_request_after_reboot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            store.request("esp32")
            completed = store.confirm_running("0.14.0")
            self.assertIsNone(completed["request"])
            self.assertEqual(completed["status"]["state"], "complete")

    def test_wrong_running_version_cannot_confirm_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            store.request("esp32")
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                store.confirm_running("0.13.1")

    def test_unknown_report_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            request = store.request("nextion")["request"]
            with self.assertRaisesRegex(ValueError, "Invalid"):
                store.report({
                    "request_id": request["id"],
                    "target": "nextion",
                    "state": "surprise",
                })

    def test_stale_request_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            store.request("nextion")
            cancelled = store.cancel()
            self.assertIsNone(cancelled["request"])
            self.assertEqual(cancelled["status"]["state"], "cancelled")

    def test_update_in_progress_cannot_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            request = store.request("nextion")["request"]
            store.report({
                "request_id": request["id"],
                "target": "nextion",
                "state": "installing",
            })
            with self.assertRaisesRegex(RuntimeError, "cannot be cancelled"):
                store.cancel()
            self.assertEqual(store.snapshot()["request"]["id"], request["id"])


if __name__ == "__main__":
    unittest.main()
