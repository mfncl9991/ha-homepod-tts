import asyncio
import logging

from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant

from .const import (
    AIRPLAY_CHANNELS,
    AIRPLAY_SAMPLE_RATE,
    GEMINI_TTS_CHANNELS,
    GEMINI_TTS_SAMPLE_RATE,
)

_LOGGER = logging.getLogger(__name__)


COMPRESSOR_FILTER = (
    "acompressor=threshold=-19dB:ratio=5:attack=7"
    ":release=450:makeup=4:detection=rms"
)


async def async_generate_wav(
    hass: HomeAssistant,
    tts_pcm: bytes,
    chime_path: str | None,
    output_path: str,
    compress_tts: bool = True,
) -> None:
    ffmpeg_bin = get_ffmpeg_manager(hass).binary

    tts_filters = f"aresample={AIRPLAY_SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=stereo"
    if compress_tts:
        tts_filters += f",{COMPRESSOR_FILTER}"

    if chime_path:
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
                f"[0:a]aresample={AIRPLAY_SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=stereo[a0];"
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
