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

Set the Raspberry API URL in the `Felicity dashboard client` menu. Wi-Fi is
configured on the Nextion display at first boot: the ESP32 scans nearby
networks, shows five SSIDs per page, and provides alpha, numeric, and symbol
keyboard layouts. Credentials are written to the `felicity_wifi` NVS namespace
only after DHCP succeeds. The compile-time SSID and password remain optional
fallback values for development builds.

If saved credentials cannot connect within 15 seconds, the setup screen opens
automatically. A successful connection is local-IP based and does not require
Internet access. The onboarding UI is drawn dynamically on the existing HMI,
so this firmware does not require a new `.tft` file.

The Home Assistant add-on must expose its HTTP port to the local network. In
the add-on Network settings, map `8000/tcp` to host port `8000`, save, and
restart the add-on. This is LAN-only access; no router port forwarding is
needed. Set the API URL to the fixed or DHCP-reserved LAN address of the Home
Assistant host, for example `http://192.168.1.10:8000`.

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

cc -std=c11 -Wall -Wextra -Werror \
  esp32/main/setup_input.c esp32/host_tests/test_setup_input.c \
  -o /tmp/felicity-setup-input-test && /tmp/felicity-setup-input-test
```
