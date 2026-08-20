# Nextion NX4827P043_011 local display

This directory contains the editable `felicity-dashboard.HMI` project and the
compiled firmware for a **Nextion NX4827P043_011**, 480×272, landscape display.
The display receives data over UART from `nextion_bridge.py` or the ESP32-C3
client. Web serving and telemetry collection remain independent of the screen.

## Page map

| ID | Page | Purpose |
|---:|---|---|
| 0 | `home` | Six summary tiles and status header |
| 1 | `pv` | Solar generation |
| 2 | `load` | Home consumption |
| 3 | `battery` | Battery state |
| 4 | `grid` | Grid state |
| 5 | `system` | Host-system health |
| 6 | `today` | Current-day energy |
| 7 | `gaps` | Current-day data coverage |

Pages must remain in this order. The bridge enables `sendxy=1`, receives touch
release coordinates, and performs navigation itself. This avoids coupling the
protocol to Nextion Hotspot component names.

## Home page layout

The header occupies `y=0..43`. Tiles use three columns and two rows:

```text
┌────────────────────────────────────────────────────────────┐
│ ◉              LIVE             01.08.2026      15:09:13 │
├──────────────────┬──────────────────┬──────────────────────┤
│ SOLAR            │ HOME LOAD        │ BATTERY              │
│ 3100 W           │ 1700 W           │ 50 %                 │
│ PV1/PV2          │ L1/L2/L3         │ 52.4 V · CHG         │
├──────────────────┼──────────────────┼──────────────────────┤
│ GRID             │ SYSTEM           │ TODAY                │
│ 230.0 V          │ 9.0 % CPU        │ 12.4 kWh             │
│ 0 W · 50.00 Hz   │ RAM · TEMP       │ LOAD · COVERAGE      │
└──────────────────┴──────────────────┴──────────────────────┘
```

Tile geometry is `x=8/165/322`, `y=50/160`, `w=150`, `h=103`. The bridge uses
these bounds for touch handling.

Numbers and all six titles are rendered with Nextion `xstr` commands over the
background. Separate text components are not required.

| Component | Content |
|---|---|
| `tTime` | Live clock |
| `tDate` | Current date |
| `tFresh` | `LIVE` or `NO DATA` |
| `tPvV`, `tPvS` | Total PV and PV1/PV2 |
| `tLoadV`, `tLoadS` | Total and per-phase load |
| `tBatV`, `tBatS` | SOC, voltage, and battery direction |
| `tGridV`, `tGridS` | Voltage, exchange, and frequency |
| `tSysV`, `tSysS` | CPU, RAM, and temperature |
| `tDayV`, `tDayS` | Generation, consumption, and coverage |

Tap a tile for its detail page. Tap the header date for `gaps`. On a detail
page, `x=0..84`, `y=0..43` is the back target.

## Detail pages and charts

Each detail page contains background picture `p0` (ID 1) and four-channel
Waveform `s0` (ID 2) at `x=12`, `y=112`, `w=456`, `h=148`. The bridge renders
the numeric block with `xstr`, then loads up to 30 recent real samples and
fills the graph incrementally so the clock and current values appear first.

Chart lines use `line` commands rather than Waveform redraws, which prevents
update flicker. Battery and System reuse the dark physical PV template while
retaining their own data and touch handling, avoiding white transition frames.

Channel colors are yellow, orange, light blue, and purple. The `gaps` page uses
one channel on a fixed 00:00–23:59 scale with at most 46 elapsed-day buckets.
High values mean data was present; dips indicate gaps. The summary shows daily
coverage, gap count, longest gap, and latest gap.

The bridge clears the left side of the header on entry, draws an 18-pixel
yin-yang symbol with primitives, and adds `BACK` plus the section title.

## Files

- `felicity-dashboard.HMI` — editable Nextion Editor source;
- `felicity-dashboard.tft` — latest compiled display firmware;
- `assets/home-background.png` — home-page source artwork;
- `assets/detail-background.png` — detail-page source artwork.

Flash `.tft` with Nextion Editor or microSD. Use `.HMI` for development;
dynamic values, navigation, and final rendering are controlled by the bridge.

## UART configuration

The UI uses **115200 baud, 8N1**. Factory speed is normally 9600. `baud=115200`
changes only the running session; `bauds=115200` also saves the power-on
default. The ESP32 client probes 9600, sends the persistent setting, and then
switches its UART to 115200. Every Nextion command ends with `FF FF FF`.

Test the Python bridge on macOS after flashing:

```bash
.venv/bin/python nextion_bridge.py \
  --port /dev/cu.usbserial-XXXX \
  --baudrate 115200 \
  --api http://127.0.0.1:8000
```

On Home Assistant OS, enable Nextion in the app and use a stable
`/dev/serial/by-id/...` path. `/dev/ttyUSB1` numbering can change after reboot.

## Pre-deployment checklist

1. Open `felicity-dashboard.HMI` and select **Compile**. The verified project
   reports `Compile Successful! 0 Errors, 0 Warnings`.
2. Upload it from Nextion Editor.
3. Confirm Waveform `s0` has ID `2` on every detail page.
4. Start FastAPI and the Felicity simulator on the development computer.
5. Run `nextion_bridge.py` through a USB-to-UART adapter.
6. Verify the live clock, green `LIVE` state, navigation, and chart updates.

The Python bridge tolerates temporary USB disconnects and retries every five
seconds.

## Updating through ESP32-C3

After the one-time migration to the ESP32 OTA partition table, the latest
verified `felicity-dashboard.tft` can be installed from Home Assistant with
**Update Nextion**. The ESP32 downloads the whole file to staging flash,
checks its size and SHA-256, requests the display's `connect` identity, and
requires model `NX4827P043_011C-Y`. It then sends 4096-byte UART packets,
waiting for `0x05` after each packet and `0x88` after display reboot.

The screen may remain blank during UART installation. Do not remove power:
unlike the ESP32 application slots, Nextion has no rollback partition. A
failed display update may require recovery from a microSD card.
