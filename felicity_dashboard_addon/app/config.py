import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("FELICITY_DB_PATH", BASE_DIR / "data" / "felicity.db"))

# Local protocol exposed by the Felicity Wi-Fi module. Keep the port on the
# trusted LAN only; the protocol does not provide application authentication.
FELICITY_HOST = os.getenv("FELICITY_HOST", "192.168.1.135")
FELICITY_PORT = int(os.getenv("FELICITY_PORT", "53970"))
FELICITY_COMMAND = "wifilocalMonitor:get dev real infor"
FELICITY_CONNECT_TIMEOUT_SECONDS = float(
    os.getenv("FELICITY_CONNECT_TIMEOUT_SECONDS", "3")
)
FELICITY_READ_TIMEOUT_SECONDS = float(
    os.getenv("FELICITY_READ_TIMEOUT_SECONDS", "1.5")
)
FELICITY_EXPECTED_BMS_PACKETS = int(
    os.getenv("FELICITY_EXPECTED_BMS_PACKETS") or "2"
)
FELICITY_MAX_RESPONSE_BYTES = int(
    os.getenv("FELICITY_MAX_RESPONSE_BYTES", str(512 * 1024))
)

SERIAL_PORT = "/dev/ttyUSB0"
BAUDRATE = 9600
SLAVE_ID = 1
REGISTER_ADDRESS = 0
REGISTER_COUNT = 10
MIN_POLL_INTERVAL_SECONDS = 5.0
POLL_INTERVAL_SECONDS = float(os.getenv("FELICITY_POLL_INTERVAL_SECONDS", "5"))
HISTORY_INTERVAL_SECONDS = float(os.getenv("FELICITY_HISTORY_INTERVAL_SECONDS", "120"))
