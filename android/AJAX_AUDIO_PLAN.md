# Ajax audio: full-stack implementation plan

## Goal

Play the doorbell's original G.722 wideband audio together with the live H.264 video, and provide a privacy-safe push-to-talk backchannel. The receive path must not transcode audio.

## Known source characteristics

- RTSP server: Ajax doorbell, TCP port 8554.
- Video: H.264, `trackID=1`, currently decoded by LibVLC.
- Incoming audio: G.722 wideband, `trackID=2`, receive-only.
- Backchannel audio: G.722, `trackID=3`, send-only.
- Ajax advertises incoming audio as `G722/16000`. G.722 audio is sampled at 16 kHz, but RTP payload type 9 uses an 8 kHz RTP timestamp clock. The audio payload itself must remain unchanged.
- Current direct-LibVLC test reaches the stream but reports `could not identify codec` for the audio track.

## Receive path

1. Capture and preserve a sanitized reference `DESCRIBE` response and verify payload type, control URLs, channel count and transport options.
2. Put a small loopback RTSP control proxy between LibVLC and Ajax. It must:
   - proxy `DESCRIBE`, `SETUP`, `PLAY`, keepalive and `TEARDOWN`;
   - handle Ajax Digest authentication using credentials kept in Android private preferences;
   - rewrite only the incoming SDP declaration `G722/16000` to the RTP-standard `G722/8000`;
   - update `Content-Length` after that edit;
   - forward all RTP/RTCP interleaved bytes unchanged;
   - never decode, encode, resample or otherwise transform incoming audio.
3. Point the existing single LibVLC player at the loopback RTSP endpoint. LibVLC then owns H.264/G.722 decoding, A/V timing and Android audio output.
4. Confirm LibVLC exposes one H.264 video track and one G.722 audio track, then confirm Android creates a PCM `AudioTrack` at the expected output rate.
5. Connect the speaker privacy control to the single player's audio volume. Muting must not interrupt video or tear down RTSP.

## Talk-back path

1. Keep the separate ONVIF backchannel negotiation for `trackID=3` because this is a send-only media direction.
2. Capture mono PCM from `AudioRecord` at 16 kHz only while the user holds `TALK`.
3. Encode PCM to G.722 and packetize it as RTP payload type 9 for the negotiated server port. This is required source encoding, not transcoding of the incoming stream.
4. Pause local playback while talking to prevent acoustic feedback; restore it immediately on release.
5. Enforce privacy coupling:
   - speaker mute immediately disables and stops the microphone/backchannel;
   - enabling the microphone automatically enables incoming sound;
   - microphone off stops transmission but may leave listening enabled;
   - no audio capture exists outside an active hold-to-talk gesture.

## Ring lifecycle

1. Keep the ONVIF PullPoint subscription active only in the home activity.
2. Open the camera only for an active `RingDetector` notification, not motion/object events or the falling edge of Ring.
3. Start one 60-second viewing timer after opening.
4. Suspend the timer during active push-to-talk and restart it on release.
5. On expiry, close RTSP/audio/backchannel resources and return to the dashboard home screen.

## Diagnostics and acceptance tests

- Log control-plane states without URLs containing credentials: SDP accepted, video track, audio track, decoder opened, AudioTrack opened, backchannel started/stopped.
- Record packet/byte counters and RTP sequence gaps, but never record audio payloads in production logs.
- Verify: audible doorbell sound, no pitch/time distortion, stable video, mute/unmute, push-to-talk at the doorbell, privacy coupling, Ring-only activation and automatic return after 60 seconds.
- Test repeated rings, network interruption, doorbell reboot, app cold start and 30-minute continuous viewing for resource leaks.
