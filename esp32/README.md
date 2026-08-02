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

Set the Raspberry API URL and temporary Wi-Fi credentials in the `Felicity
dashboard client` menu. Credentials are compile-time only for now; captive
portal provisioning will be added separately.

The Home Assistant add-on must expose its HTTP port to the local network. In
the add-on Network settings, map `8000/tcp` to host port `8000`, save, and
restart the add-on. This is LAN-only access; no router port forwarding is
needed. Set the API URL to the fixed or DHCP-reserved LAN address of the Home
Assistant host, for example `http://192.168.1.10:8000`.

The client reads `/api/device/current`, `/api/device/chart`, the slow-changing
`/api/device/summary`, and the timestamp-only `/api/device/gaps` endpoint.
Tapping the date area opens the coverage page without loading full telemetry
rows from SQLite. System and Today values refresh every 60 seconds.

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
