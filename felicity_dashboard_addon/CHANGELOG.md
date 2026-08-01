# Changelog

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
