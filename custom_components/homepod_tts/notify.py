import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pyatv
from pyatv.interface import AppleTV

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import async_generate_wav
from .const import (
    CONF_CHIME_ENABLED,
    CONF_CHIME_PATH,
    CONF_COMPRESS_TTS,
    CONF_DEFAULT_VOLUME,
    CONF_GEMINI_API_KEY,
    CONF_HOMEPOD_IDENTIFIER,
    CONF_RESTORE_VOLUME,
    CONF_TTS_VOICE,
    DEFAULT_CHIME_ENABLED,
    DEFAULT_COMPRESS_TTS,
    DEFAULT_RESTORE_VOLUME,
    DEFAULT_TTS_VOICE,
    DEFAULT_VOLUME,
    DOMAIN,
)
from .tts_client import GeminiTTSClient

_LOGGER = logging.getLogger(__name__)

DEFAULT_CHIME_FILE = str(Path(__file__).parent / "sounds" / "chime.mp3")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entity = HomePodTTSNotifyEntity(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["entity"] = entity
    async_add_entities([entity])


class HomePodTTSNotifyEntity(NotifyEntity):

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._lock = asyncio.Lock()
        self._atv: AppleTV | None = None
        self._tts_client: GeminiTTSClient | None = None

        self._attr_unique_id = f"{entry.entry_id}_notify"
        self._attr_name = entry.data.get(CONF_NAME, "HomePod TTS")

    @property
    def _identifier(self) -> str:
        return self._entry.data[CONF_HOMEPOD_IDENTIFIER]

    @property
    def _api_key(self) -> str:
        return self._entry.data[CONF_GEMINI_API_KEY]

    @property
    def _chime_enabled(self) -> bool:
        return self._entry.options.get(CONF_CHIME_ENABLED, DEFAULT_CHIME_ENABLED)

    @property
    def _chime_path(self) -> str:
        return self._entry.options.get(CONF_CHIME_PATH, "") or DEFAULT_CHIME_FILE

    @property
    def _volume(self) -> float:
        return self._entry.options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME)

    @property
    def _restore_volume(self) -> bool:
        return self._entry.options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME)

    @property
    def _voice(self) -> str:
        return self._entry.options.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE)

    @property
    def _compress_tts(self) -> bool:
        return self._entry.options.get(CONF_COMPRESS_TTS, DEFAULT_COMPRESS_TTS)

    def _get_tts_client(self) -> GeminiTTSClient:
        if self._tts_client is None:
            session = async_get_clientsession(self._hass)
            self._tts_client = GeminiTTSClient(
                self._api_key, session, self._voice
            )
        return self._tts_client

    async def _async_get_connection(self) -> AppleTV:
        if self._atv is not None:
            return self._atv

        identifier = self._identifier
        apple_tv_entries = self._hass.config_entries.async_entries("apple_tv")

        credentials: dict[int, str] = {}
        for atv_entry in apple_tv_entries:
            uid = atv_entry.unique_id or atv_entry.entry_id
            if uid == identifier:
                credentials = atv_entry.data.get("credentials", {})
                break

        atvs = await pyatv.scan(
            self._hass.loop,
            identifier=identifier,
            timeout=5,
        )
        if not atvs:
            raise ConnectionError(
                f"Could not find HomePod with identifier {identifier}"
            )

        conf = atvs[0]
        for protocol_int, cred in credentials.items():
            protocol = pyatv.const.Protocol(int(protocol_int))
            conf.set_credentials(protocol, cred)

        self._atv = await pyatv.connect(conf, self._hass.loop)
        return self._atv

    async def _async_disconnect(self) -> None:
        if self._atv is not None:
            self._atv.close()
            self._atv = None

    async def async_play_tts(
        self,
        message: str,
        *,
        chime: bool | None = None,
        volume: float | None = None,
        compress: bool | None = None,
    ) -> None:
        if chime is None:
            chime = self._chime_enabled
        if volume is None:
            volume = self._volume
        if compress is None:
            compress = self._compress_tts

        async with self._lock:
            tmp_path = None
            previous_volume: float | None = None
            try:
                tts_client = self._get_tts_client()
                _LOGGER.debug("Synthesizing TTS for: %s", message)
                tts_pcm = await tts_client.synthesize(message)

                fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="homepod_tts_")
                os.close(fd)

                chime_path = self._chime_path if chime else None
                await async_generate_wav(
                    self._hass, tts_pcm, chime_path, tmp_path,
                    compress_tts=compress,
                )

                atv = await self._async_get_connection()

                if self._restore_volume:
                    with contextlib.suppress(Exception):
                        previous_volume = atv.audio.volume

                with contextlib.suppress(Exception):
                    await atv.audio.set_volume(volume * 100)

                _LOGGER.debug("Streaming %s to HomePod", tmp_path)
                await atv.stream.stream_file(tmp_path)

            except ConnectionError:
                _LOGGER.warning(
                    "Lost connection to HomePod, will reconnect on next call"
                )
                await self._async_disconnect()
            except Exception:
                _LOGGER.exception("Failed to send TTS to HomePod")
                await self._async_disconnect()
            finally:
                if previous_volume is not None:
                    with contextlib.suppress(Exception):
                        atv = self._atv
                        if atv is not None:
                            await atv.audio.set_volume(previous_volume)

                if tmp_path is not None:
                    with contextlib.suppress(FileNotFoundError):
                        os.unlink(tmp_path)

    async def async_send_message(self, message: str, **kwargs: Any) -> None:
        await self.async_play_tts(message)

    async def async_will_remove_from_hass(self) -> None:
        await self._async_disconnect()
