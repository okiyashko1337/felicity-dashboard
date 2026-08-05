# ESP32-C3 Nextion client

This is the lightweight replacement for `nextion_bridge.py`. The Raspberry Pi
continues to collect and store telemetry; the ESP32-C3 reads compact HTTP
endpoints and drives the existing NX4827P043 HMI at 115200 baud.

## Wiring

- ESP32 GPIO4 (TX) -> Nextion RX
- ESP32 GPIO5 (RX) <- Nextion TX
- ESP32 GND <-> Nextion GND
- Nextion +5V from its own USB-A 5V supply lead
- ESP32 from a separate USB-C port; do not join the two +5V rails

## Build for the board

```sh
source "$HOME/.espressif/tools/activate_idf_v6.0.2.sh"
idf.py -C esp32 -B build-hardware \
  -DSDKCONFIG=sdkconfig.hardware \
  -DSDKCONFIG_DEFAULTS=sdkconfig.defaults menuconfig
idf.py -C esp32 -B build-hardware build
```

The hardware configuration deliberately disables the ESP32-C3 USB PHY and the
secondary USB console. On this board the active USB PHY can suppress 2.4 GHz
transmission even though Wi-Fi scanning still works. USB flashing remains
available through the ROM bootloader; runtime logs use UART0 instead.

On its first boot the board creates an open Wi-Fi network named
`Felicity-Setup-XXXX`. Connect a phone or laptop to it, open
`http://192.168.4.1`, and enter the home Wi-Fi network, password, and Raspberry
API URL. The settings are stored in the ESP32's NVS flash; the password is not
printed to the serial log.

The Home Assistant add-on must expose its HTTP port to the local network. In
the add-on Network settings, map `8000/tcp` to host port `8000`, save, and
restart the add-on. This is LAN-only access; no router port forwarding is
needed. Set the API URL to the fixed or DHCP-reserved LAN address of the Home
Assistant host, for example `http://192.168.1.10:8000`.

To reopen setup later, hold the ESP32-C3 Super Mini **BOOT** button for three
seconds while it is running, then release it. The board clears only its saved
Felicity Wi-Fi/API settings, restarts, and advertises `Felicity-Setup-XXXX`.
Pressing RESET or briefly pressing BOOT does not erase the settings.

The client reads `/api/device/current`, `/api/device/chart`, the slow-changing
`/api/device/summary`, and the timestamp-only `/api/device/gaps` endpoint.
Tapping the date area opens the coverage page without loading full telemetry
rows from SQLite. System and Today values refresh every 60 seconds.

Energy, battery, grid, daily, and gap charts use a fixed `00:00-24:00`
timeline with 180 eight-minute samples. The System chart instead shows the
latest ten minutes with up to 60 ten-second samples. For full System detail,
set the Home Assistant add-on `system_interval` option to `10` seconds.

## Emulator build

The emulator configuration avoids Wi-Fi and prints every Nextion command as an
`NX>` log line using deterministic sample data:

```sh
source "$HOME/.espressif/tools/activate_idf_v6.0.2.sh"
idf.py -C esp32 -B build-qemu \
  -DSDKCONFIG=sdkconfig.qemu.generated \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.qemu" build
```

QEMU cannot emulate the ESP32-C3 radio or a physical Nextion display. This mode
still verifies boot, scheduling, JSON-independent rendering, and the exact UART
commands. The frame parser has a native host test:

```sh
cc -std=c11 -Wall -Wextra -Werror \
  esp32/main/touch_parser.c esp32/host_tests/test_touch_parser.c \
  -o /tmp/felicity-touch-test && /tmp/felicity-touch-test
```

To replace the deterministic samples with the live Raspberry API, build a
separate image with QEMU's virtual Ethernet interface:

```sh
idf.py -C esp32 -B build-qemu-live \
  -DSDKCONFIG=sdkconfig.qemu-live.generated \
  -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.qemu;sdkconfig.qemu-live" build
idf.py -C esp32 -B build-qemu-live qemu
```

This live mode is only for the emulator. The hardware build continues to use
the ESP32-C3 Wi-Fi radio. The log-only emulator cycles through all dashboard
pages every five seconds. UART-bridge mode instead uses touch frames from the
physical Nextion and never changes pages by itself.

## Physical Nextion from QEMU

On macOS, the live emulator can be connected bidirectionally to a Nextion on a
USB-UART adapter. Drawing commands go to the display and touch frames return to
QEMU:

```sh
python3 esp32/tools/qemu_nextion_bridge.py \
  --qemu /path/to/qemu-system-riscv32 \
  --flash build-qemu-live/flash_image.bin \
  --serial /dev/cu.usbserial-XXXX
```

The display and USB-UART must share ground. Keep the Nextion on its separate
5 V supply and do not connect another UART host at the same time.
