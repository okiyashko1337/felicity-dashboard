from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "felicity.db"

SERIAL_PORT = "/dev/ttyUSB0"
BAUDRATE = 9600
SLAVE_ID = 1
REGISTER_ADDRESS = 0
REGISTER_COUNT = 10
POLL_INTERVAL_SECONDS = 2.0

