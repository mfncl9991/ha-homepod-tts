import asyncio
import base64
import logging

import aiohttp
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant

from .const import GEMINI_TTS_BASE_URL, GEMINI_TTS_CHANNELS, GEMINI_TTS_SAMPLE_RATE

_LOGGER = logging.getLogger(__name__)


class GeminiTTSClient:
    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        voice: str = "Aoede",
        model: str = "gemini-2.5-flash-preview-tts",
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._voice = voice
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def voice(self) -> str:
        return self._voice

    async def synthesize(
        self,
        text: str,
        *,
        prompt: str | None = None,
    ) -> bytes:
        url = f"{GEMINI_TTS_BASE_URL}{self._model}:generateContent?key={self._api_key}"

        full_text = f"{prompt}: {text}" if prompt else text

        payload = {
            "contents": [{"parts": [{"text": full_text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice}}
                },
            },
        }

        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Gemini TTS API returned {resp.status}: {body}")
            data = await resp.json()

        try:
            audio_b64 = data["candidates"][0]["content"]["parts"][0]["inlineData"][
                "data"
            ]
        except (KeyError, IndexError) as err:
            raise RuntimeError(
                f"Unexpected Gemini TTS response structure: {err}"
            ) from err

        return base64.b64decode(audio_b64)

    async def generate_music(self, prompt: str) -> bytes:
        """Generate music via Gemini Lyria 3 API. Returns MP3 bytes."""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"lyria-3-clip-preview:generateContent?key={self._api_key}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
        }

        timeout = aiohttp.ClientTimeout(total=120)
        async with self._session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Lyria API returned {resp.status}: {body}")
            data = await resp.json()

        try:
            for part in data["candidates"][0]["content"]["parts"]:
                if "inlineData" in part:
                    return base64.b64decode(part["inlineData"]["data"])
        except (KeyError, IndexError):
            pass

        raise RuntimeError("No audio data in Lyria response")

    async def validate_api_key(self) -> bool:
        try:
            await self.synthesize("test")
            return True
        except RuntimeError:
            return False


class HATTSClient:
    """TTS client backed by any `tts.*` entity configured in Home Assistant.

    Uses the same media_source pipeline as the `tts.speak` action (and
    chime_tts), so it works with edge_tts, google_translate, piper, Nabu
    Casa Cloud, etc. — whatever the user has set up. Mirrors
    GeminiTTSClient's `synthesize()` interface: returns raw PCM (s16le,
    GEMINI_TTS_SAMPLE_RATE/CHANNELS), decoding via ffmpeg since most engines
    return MP3 or WAV.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        engine: str,
        language: str | None = None,
        voice: str | None = None,
    ) -> None:
        self._hass = hass
        self._engine = engine
        self._language = language
        self._voice = voice

    @property
    def model(self) -> str:
        return self._engine

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def language(self) -> str | None:
        return self._language

    @property
    def voice(self) -> str:
        return self._voice or ""

    async def synthesize(
        self,
        text: str,
        *,
        prompt: str | None = None,
    ) -> bytes:
        # Most HA TTS engines have no style-prompt concept; fold it into the text.
        full_text = f"{prompt}. {text}" if prompt else text

        from homeassistant.components import tts

        options: dict = {}
        if self._voice:
            options["voice"] = self._voice

        media_source_id = await asyncio.to_thread(
            tts.media_source.generate_media_source_id,
            hass=self._hass,
            message=full_text,
            engine=self._engine,
            language=self._language or None,
            options=options or None,
        )

        _extension, audio_bytes = await tts.async_get_media_source_audio(
            self._hass, media_source_id
        )

        return await self._async_decode_to_pcm(audio_bytes)

    async def _async_decode_to_pcm(self, audio_bytes: bytes) -> bytes:
        ffmpeg_bin = get_ffmpeg_manager(self._hass).binary
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_bin,
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ar",
            str(GEMINI_TTS_SAMPLE_RATE),
            "-ac",
            str(GEMINI_TTS_CHANNELS),
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=audio_bytes)

        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed to decode TTS audio (rc={proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )

        return stdout
