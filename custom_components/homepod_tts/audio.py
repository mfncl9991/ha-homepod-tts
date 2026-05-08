import asyncio
import logging

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant

from .const import (
    AIRPLAY_CHANNELS,
    AIRPLAY_SAMPLE_RATE,
    COMPRESS_PRESETS,
    GEMINI_TTS_CHANNELS,
    GEMINI_TTS_SAMPLE_RATE,
)

_LOGGER = logging.getLogger(__name__)


async def _get_audio_duration(ffmpeg_bin: str, path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_bin, "-i", path, "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    for line in stderr.decode(errors="replace").splitlines():
        if "Duration:" in line:
            parts = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = parts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


async def async_generate_wav(
    hass: HomeAssistant,
    tts_pcm: bytes,
    chime_path: str | None,
    output_path: str,
    compress_preset: str = "moderate",
    offset_ms: int = 0,
    chime_volume: float = 1.0,
) -> None:
    ffmpeg_bin = get_ffmpeg_manager(hass).binary

    compressor = COMPRESS_PRESETS.get(compress_preset)

    tts_filters = (
        f"aresample={AIRPLAY_SAMPLE_RATE},"
        f"aformat=sample_fmts=s16:channel_layouts=stereo"
    )
    if compressor:
        tts_filters += f",{compressor}"

    if chime_path:
        chime_filters = (
            f"aresample={AIRPLAY_SAMPLE_RATE},"
            f"aformat=sample_fmts=s16:channel_layouts=stereo"
        )

        if chime_volume != 1.0:
            chime_filters += f",volume={chime_volume:.2f}"

        if offset_ms < 0:
            duration = await _get_audio_duration(ffmpeg_bin, chime_path)
            trim_end = max(0.1, duration + offset_ms / 1000)
            chime_filters += f",atrim=end={trim_end:.3f}"
        elif offset_ms > 0:
            chime_filters += f",apad=pad_dur={offset_ms / 1000:.3f}"

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", chime_path,
            "-f", "s16le",
            "-ar", str(GEMINI_TTS_SAMPLE_RATE),
            "-ac", str(GEMINI_TTS_CHANNELS),
            "-i", "pipe:0",
            "-filter_complex",
            (
                f"[0:a]{chime_filters}[a0];"
                f"[1:a]{tts_filters}[a1];"
                "[a0][a1]concat=n=2:v=0:a=1[out]"
            ),
            "-map", "[out]",
            output_path,
        ]
    else:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "s16le",
            "-ar", str(GEMINI_TTS_SAMPLE_RATE),
            "-ac", str(GEMINI_TTS_CHANNELS),
            "-i", "pipe:0",
            "-af", tts_filters,
            output_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate(input=tts_pcm)

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace")
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {err_msg}")

    _LOGGER.debug("Generated WAV at %s", output_path)
