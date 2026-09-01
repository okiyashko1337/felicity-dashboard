# Felicity for iOS

Native iPhone and iPad client for the Felicity energy and Ajax camera system.

## Open and run

1. Open `FelicityDashboard.xcodeproj` in Xcode.
2. Select the `FelicityDashboard` target and open **Signing & Capabilities**.
3. Enable **Automatically manage signing** and choose your **Personal Team**.
4. Connect the iPad, trust the Mac, enable Developer Mode and press Run.

The default server is `http://homeassistant.local:8000`. Tap the yin-yang mark
to change it. The app requests local-network access on first connection.

The first milestone implements the adaptive energy home screen and its local
API lifecycle. Camera, Events and Profile G Archive are added as vertical
slices on top of the contracts documented in
[`Docs/ARCHITECTURE.md`](Docs/ARCHITECTURE.md) and the behavioural checklist in
[`Docs/PORTING_PLAN.md`](Docs/PORTING_PLAN.md).
