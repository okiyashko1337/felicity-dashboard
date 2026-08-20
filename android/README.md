# Felicity Android kiosk

Native Android client for the Felicity Dashboard LAN API. It is an alternative
to the ESP32 + Nextion monitor: both clients use the same `/api/device/*`
endpoints, but the Android version runs directly on an Echo Show 5 or another
dedicated landscape display.

The reference device is an Echo Show 5 (2nd generation, `cronos`) running
Android 11 at 960×480. The app has no Google Services, WebView, Home Assistant
token, or third-party Android library dependency.

## Features

- six live Solar, Home Load, Battery, Grid, System, and Today cards;
- detail pages with labelled time and value axes;
- current conditions and a seven-day Open-Meteo forecast;
- Android device location with a saved city override when a provider is
  unavailable;
- visible and media-volume-controlled click feedback for active touch targets;
- retained last telemetry while the server reconnects;
- landscape immersive mode, keep-screen-on, boot receiver, and optional HOME
  launcher role;
- on-device Settings page for API address, weather city, refresh intervals,
  kiosk state, and client/server versions.

Tap the yin-yang mark on the home page to open Settings. It is deliberately
inactive on detail pages. Tap the weather item in the header for the forecast.

## Server setup

The Android device must reach the Felicity HTTP port on the trusted LAN. For
the Home Assistant app, map TCP port `8000` in its network configuration. Do
not forward this port on the Internet: the compact device API is intentionally
unauthenticated for local displays.

The initial address is `http://homeassistant.local:8000`. Open Settings and
replace it with the Home Assistant IP when mDNS is not available.

## Build

Install Android SDK 32 and a Java 11+ runtime, then run:

```sh
cd android
./gradlew :app:assembleDebug
```

The APK is written to `app/build/outputs/apk/debug/app-debug.apk`.

## Install and kiosk mode

With network ADB enabled on the Android display:

```sh
adb connect DISPLAY_IP:5555
adb -s DISPLAY_IP:5555 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s DISPLAY_IP:5555 shell cmd package set-home-activity \
  io.github.okiyashko1337.felicitydashboard/.MainActivity
```

The last command is optional but recommended for a dedicated display. It makes
Felicity Dashboard the HOME app, which provides reliable cold-start recovery.
The manifest also contains a `BOOT_COMPLETED` receiver.

Location permission is used only to choose forecast coordinates. If the device
has no functional fused/network location backend, open Settings, tap **Weather
location**, and enter its city once. The resulting coordinates are stored in
the app's private preferences.

## Refresh schedule

- `/api/device/current`: 2 seconds;
- `/api/status`: 5 seconds;
- `/api/device/summary`: 10 seconds;
- System chart: 10 seconds while visible;
- daily charts: immediately on entry, then 60 seconds while visible;
- Open-Meteo forecast: 15 minutes.

The server caches `/api/device/summary` for ten seconds, allowing Android and
Nextion displays to refresh together without repeating the daily aggregation.
