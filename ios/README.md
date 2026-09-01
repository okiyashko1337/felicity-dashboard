# Felicity for iOS

Native iPhone and iPad client for the Felicity energy and Ajax camera system.

## Open and run

1. Open `FelicityDashboard.xcodeproj` in Xcode.
2. Select the `FelicityDashboard` target and open **Signing & Capabilities**.
3. Enable **Automatically manage signing** and choose your **Personal Team**.
4. Connect the iPad, trust the Mac, enable Developer Mode and press Run.

The default server is `http://homeassistant.local:8000`. Tap the yin-yang mark
to change it. The app requests local-network access on first connection.

## Live cameras and events

Version 0.3 includes the first native camera and 3ye event slices:

- direct ONVIF discovery from the Ajax recorder;
- direct RTSP-over-TCP H.264/H.265 playback with Apple hardware decoding;
- a smooth static-preview camera wall with no background stream churn;
- native pinch, pan and double-tap reset;
- remembered LQ/HQ choice per camera;
- last-frame JPEG continuity while a stream reconnects or changes quality;
- a lightweight authenticated 3ye event wall with static thumbnails;
- camera/all-camera scope plus person, vehicle, animal and face filters; and
- automatic IPv4 preference for `.local` Felicity hosts whose advertised IPv6
  address is unreachable.

Open **Settings → Ajax recorder · ONVIF**, enter the recorder address and its
ONVIF credentials, then tap **Discover cameras**. The camera button on the home
screen opens the selected camera; tap its name in Live to switch cameras. Open
**Events** from either the energy or Live header. Event images are fetched with
the 3ye credentials stored in Keychain; generic motion is deliberately excluded.
Passwords are stored in Keychain and are never written into the repository.

Profile G Archive and audio follow as separate vertical slices on top of the
contracts documented in
[`Docs/ARCHITECTURE.md`](Docs/ARCHITECTURE.md) and the behavioural checklist in
[`Docs/PORTING_PLAN.md`](Docs/PORTING_PLAN.md).
