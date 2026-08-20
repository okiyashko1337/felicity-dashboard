# Felicity Energy Dashboard

This Home Assistant app polls a Felicity IVGM Wi-Fi module on the local
network, stores compact history in `/data/felicity.db`, and exposes the web
dashboard through Home Assistant Ingress.

## Configuration

| Option | Description |
|---|---|
| `inverter_host` | Local IP address of the Felicity Wi-Fi module |
| `inverter_port` | Local protocol port, normally `53970` |
| `poll_interval` | Inverter polling interval in seconds; minimum and default are 5 |
| `expected_bms_packets` | BMS packets expected before the TCP session closes |
| `system_interval` | Host-system metrics interval in seconds |
| `nextion_enabled` | Starts the optional local UART Nextion bridge |
| `nextion_port` | Stable serial path, preferably `/dev/serial/by-id/...` |
| `nextion_baudrate` | Nextion UART rate; the current UI uses `115200` |

The display can be connected later. `nextion_enabled` defaults to `false`, so
an app update does not alter an existing dashboard. Once the display is
flashed, enable the option, select its stable serial path, and restart the app.
See [`nextion/`](../nextion/) for protocol and editor-project details.

Open the dashboard with **Open Web UI** or the **Felicity Energy** sidebar
entry.

## Local display API

The direct HTTP port is not published by default. Ingress handles authenticated
web access. To use an ESP32 or Android display, expose `8000/tcp` only on the
trusted LAN in the app's **Network** settings and use the Home Assistant host,
for example `http://192.168.1.10:8000`.

The compact device API has no user authentication. Do not forward it from the
router.

## Collection and retention

Polling runs no faster than every five seconds in this app. The collector waits
for the inverter packet and all configured BMS packets, acknowledges the full
response, closes the write side, waits for the peer to finish, and then closes
the TCP session.

The database is included in app backups. The app stops during backup to create
a consistent SQLite snapshot.

Full telemetry is retained only as one current row. Compact history stores the
important fields every two minutes; raw packets are not written. On first boot
after a storage migration, old history is thinned and SQLite reclaims unused
space, so startup can take longer on a Raspberry Pi. Diagnostic gap timestamps
are kept for three days and system metrics for 48 hours.

## Security

- Never expose the inverter's unauthenticated TCP port `53970`.
- Keep the optional device API port on the LAN only.
- Prefer Ingress for browser access and a VPN for remote LAN access.
