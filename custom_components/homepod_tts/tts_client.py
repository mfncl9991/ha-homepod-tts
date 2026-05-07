import base64
import logging

import aiohttp

from .const import GEMINI_TTS_ENDPOINT

_LOGGER = logging.getLogger(__name__)


class GeminiTTSClient:

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        voice: str = "Kore",
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        url = f"{GEMINI_TTS_ENDPOINT}?key={self._api_key}"
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": self._voice}
                    }
                },
            },
        }

        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Gemini TTS API returned {resp.status}: {body}"
                )
            data = await resp.json()

        try:
            audio_b64 = data["candidates"][0]["content"]["parts"][0][
                "inlineData"
            ]["data"]
        except (KeyError, IndexError) as err:
            raise RuntimeError(
                f"Unexpected Gemini TTS response structure: {err}"
            ) from err

        return base64.b64decode(audio_b64)

    async def validate_api_key(self) -> bool:
        try:
            await self.synthesize("test")
            return True
        except RuntimeError:
            return False
