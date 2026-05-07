# HomePod TTS — Custom Home Assistant Integration

A custom Home Assistant integration that plays TTS announcements with an optional chime sound on Apple HomePod, using **Google Gemini TTS** for speech synthesis and **pyatv** for AirPlay streaming.

## Why?

Home Assistant's built-in `apple_tv` integration uses pyatv for AirPlay streaming, which delegates audio decoding to the `miniaudio` library. `miniaudio` frequently fails with `DecodeError('failed to init decoder', -1)` when streaming TTS audio to HomePod — a long-standing regression ([#71569](https://github.com/home-assistant/core/issues/71569), [#97075](https://github.com/home-assistant/core/issues/97075), [#123176](https://github.com/home-assistant/core/issues/123176)).

This integration **bypasses the bug entirely** by:
1. Generating TTS audio via Google Gemini API
2. Concatenating chime + TTS with ffmpeg into a local WAV file
3. Streaming the local file via pyatv's `stream_file()` — which uses `miniaudio.decode_file()` (working) instead of `miniaudio.stream_any()` (broken)

## Features

- Chime + TTS announcements on HomePod via AirPlay
- Google Gemini TTS with configurable voice
- Dynamic range compression (matching `chime_tts` settings)
- Volume control with automatic restore after playback
- Custom `homepod_tts.say` service with per-call overrides
- Standard `notify.send_message` entity support
- Config flow UI — no YAML configuration needed

## Requirements

- Home Assistant 2024.4+
- Apple TV integration configured with your HomePod(s)
- Google Gemini API key ([get one here](https://aistudio.google.com/apikey))
- ffmpeg (included in HAOS by default)

## Installation

### HACS (Manual Repository)

1. Open HACS → Integrations → three-dot menu → **Custom repositories**
2. Add this repository URL, category: **Integration**
3. Search for "HomePod TTS" and install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/homepod_tts/` to your HA config directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **HomePod TTS**
3. Select your HomePod (from Apple TV integration entries)
4. Enter your Gemini API key

### Options (Settings → Devices → HomePod TTS → Configure)

| Option | Default | Description |
|---|---|---|
| Chime | On | Play chime sound before announcement |
| Chime path | bundled soft chime | Path to custom chime MP3/WAV |
| Volume | 0.5 | Announcement volume (0.0–1.0) |
| Restore volume | On | Restore previous volume after playback |
| TTS voice | Aoede | Gemini TTS voice |
| Compress TTS | On | Dynamic range compression on TTS audio |

## Usage

### Custom Service (recommended)

```yaml
action: homepod_tts.say
data:
  entity_id: notify.homepod_mini_hall
  message: "Paczka czeka w skrytce numer 5"
  volume_level: 0.55        # optional override
  chime: true                # optional override
  compress: true             # optional override
```

### Notify Entity

```yaml
action: notify.send_message
target:
  entity_id: notify.homepod_mini_hall
data:
  message: "Paczka czeka w skrytce numer 5"
```

### Automation Example

```yaml
- alias: Bedtime announcement
  trigger:
    - platform: time
      at: "20:00:00"
  action:
    - action: conversation.process
      data:
        text: "Generate a short bedtime message for a child"
        agent_id: conversation.claude
      response_variable: ai_response
    - action: homepod_tts.say
      data:
        entity_id: notify.homepod_mini_hall
        message: "{{ ai_response.response.speech.plain.speech }}"
        volume_level: 0.55
```

## Audio Pipeline

```
Gemini TTS API → PCM (24kHz mono) ─┐
                                    ├─ ffmpeg (concat + resample + compress) → WAV (44.1kHz stereo)
Chime MP3 ──────────────────────────┘                                              │
                                                                    pyatv stream_file() → HomePod
```

- Compression is applied **only to TTS audio**, not the chime
- Compression settings: `threshold=-19dB, ratio=5, attack=7ms, release=450ms, makeup=4dB, RMS detection`

## How It Works (Technical Details)

The miniaudio decode bug in pyatv affects `InternetSource.open()` which is used when streaming from HTTP URLs. When given a **local file path**, pyatv routes through `FileSource.open()` → `miniaudio.decode_file()` — a completely separate, working code path.

This integration exploits that by:
1. Calling Gemini TTS REST API to get raw PCM audio
2. Using ffmpeg to concatenate the chime and TTS audio, resample to 44.1kHz stereo, and optionally apply dynamic range compression
3. Writing the result to a temporary WAV file
4. Calling `pyatv.stream.stream_file()` with the local path
5. Cleaning up the temp file after playback

## License

MIT
