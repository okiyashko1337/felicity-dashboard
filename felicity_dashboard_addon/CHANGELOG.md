# Changelog

## 0.10.4

- Fix energy, battery, grid, daily, and gap charts to the full current day.
- Use 180 eight-minute bins with an explicit `00-06-12-18-24` time axis.
- Leave future and missing intervals empty instead of drawing misleading zeroes.
- Give the System chart a detailed rolling ten-minute window with 60 ten-second bins.
- Change the recommended Raspberry system collection interval to ten seconds.

## 0.10.3

- Add a compact slow-changing System and Today summary endpoint for ESP32.
- Restore all six live home tiles without adding new telemetry storage.
- Show real CPU, RAM, temperature, disk, daily energy, coverage, and grid totals on detail pages.
- Poll summary data every 60 seconds while keeping inverter values at the fast interval.

## 0.10.2

- Use the Home Assistant build version as the single UI and app version source.
- Inject the version into the dashboard HTML, status API, and no-cache response header.
- Remove the stale hard-coded UI 0.7.0 marker.
- Add a client-side total solar-power line computed from PV1 and PV2 without new database fields.

## 0.10.1

- Add a compact timestamp-only API for today's telemetry coverage.
- Complete the ESP32-C3 GAPS page with coverage, duration, latest interval, and graph rendering.
- Include the GAPS page in deterministic QEMU navigation and keep its BACK touch behavior.

## 0.10.0

- Add compact current-telemetry and chart endpoints for constrained IoT clients.
- Add an ESP32-C3 client for the existing NX4827P043 Nextion dashboard.
- Preserve touch navigation and render live detail graphs without a local Raspberry Pi display bridge.
- Add separate hardware and deterministic QEMU builds plus native touch-frame parser tests.

## 0.9.5

- Keep touch input responsive while API requests run in bounded background workers.
- Recover Nextion coordinate reporting automatically and accept both press and release events.
- Bound and reset the UART parser buffer so damaged frames cannot accumulate indefinitely.
- Close every SQLite connection deterministically to prevent long-running resource degradation.

## 0.9.4

- Load the TODAY card from the persisted daily energy aggregate instead of scanning raw telemetry.
- Keep the heavier data-gap calculation separate and request it only when opening the gaps page.
- Prevent the TODAY value from becoming stale when a full-day raw query exceeds the bridge timeout.

## 0.9.3

- Replace the wordmark with a clipped-safe 18px yin-yang drawn by Nextion primitives.
- Show BACK and the current section name on every detail page.
- Open legacy Battery and System views on an already-dark template to eliminate white flashes.
- Redraw all six home-card headings with one consistent font and color.

## 0.9.2

- Remove the last legacy logo pixels before drawing compact detail headers.
- Give Battery the same complete dark canvas and color-coded metrics as System.
- Match the SYSTEM home-card title color to the other card headings.

## 0.9.1

- Fit the compact Felicity brand and full page title on detail headers.
- Replace the legacy light System page with the standard dark dashboard canvas.
- Color-code CPU, RAM, temperature, and disk metrics to match their chart lines.

## 0.9.0

- Completed PV, load, battery, grid, system, today, and data-gap detail charts.
- Aligned chart timestamps with the actual end of each live trace.
- Added a fixed 00:00–23:59 daily scale and stepped rendering for data gaps.
- Removed overlapping time labels and cleaned up the compact detail-page header.
- Added battery-module details and disk usage to the local display.

## 0.8.0

- Optional UART bridge for the Nextion NX4827P043_011 local display.
- Six-tile home screen protocol with dedicated detail pages.
- Tapping today's date opens daily telemetry gap statistics.
- Current values render before a sparse, incremental chart replay.
- Smooth 115200-baud updates without unreliable transparent waveform transfers.

## 0.7.0

- Gap statistics with coverage, gap count, and longest missing interval.
- Dashed, translucent bridges make missing telemetry visible on line charts.
- Missing days remain empty and are marked explicitly in period charts.

## 0.6.1

- PV-to-consumption energy coverage for the selected history period.
- Chart legend visibility persists through live refreshes and page reloads.
- Human-readable inverter warning codes in the diagnostics card.

## 0.6.0

- Detail-chart scales for 15 minutes, 1 hour, 6 hours, and the current day.
- Fixed current-day timeline from 00:00 through 23:59 with future time left empty.
- Five secondary diagnostic cards for BMS, temperatures, DC/MPPT, and backup state.

## 0.5.1

- Prevent Home Assistant Ingress and browsers from reusing stale dashboard HTML.
- Add a visible UI version marker for quick deployment verification.

## 0.5.0

- Clear live-data freshness state without a countdown progress bar.
- Frame number and exact source update timestamp.
- Ticking local clock and date beside the data status.

## 0.4.0

- Five interactive summary cards with one focused detail chart.
- History periods for day, week, month, and all saved data.
- Persistent daily energy aggregates for fast long-range statistics.

## 0.3.0

- Daily history navigation with local-date boundaries.
- Energy statistics for PV, load, grid import/export, and battery charge/discharge.
- Dedicated battery and BMS charts.

## 0.2.0

- Initial Home Assistant OS app.
- Authenticated Ingress dashboard.
- Persistent inverter and Raspberry Pi history.
