import unittest
from unittest.mock import patch

import collector


class CollectorResilienceTests(unittest.TestCase):
    def test_retry_delay_backs_off_and_is_bounded(self) -> None:
        with patch.object(collector, "FELICITY_MAX_RETRY_DELAY_SECONDS", 60.0):
            self.assertEqual(collector.retry_delay(2.0, 1), 2.0)
            self.assertEqual(collector.retry_delay(2.0, 2), 4.0)
            self.assertEqual(collector.retry_delay(2.0, 4), 16.0)
            self.assertEqual(collector.retry_delay(2.0, 8), 60.0)


if __name__ == "__main__":
    unittest.main()
