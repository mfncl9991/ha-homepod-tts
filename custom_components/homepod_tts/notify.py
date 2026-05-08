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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .audio import async_generate_wav
from .cache import (
    cache_key,
    enforce_max_size,
    get_cached,
    put_cache,
)
from .const import (
    CONF_CACHE_ENABLED,
    CONF_CACHE_MAX_MB,
    CONF_CHIME_ENABLED,
    CONF_CHIME_OFFSET,
    CONF_CHIME_PATH,
    CONF_CHIME_VOLUME,
    CONF_COMPRESS_TTS,
    CONF_DEFAULT_VOLUME,
    CONF_GEMINI_API_KEY,
    CONF_HOMEPOD_IDENTIFIER,
    CONF_RESTORE_VOLUME,
    CONF_TTS_MODEL,
    CONF_TTS_PROMPT,
    CONF_TTS_VOICE,
    DEFAULT_CACHE_ENABLED,
    DEFAULT_CACHE_MAX_MB,
    DEFAULT_CHIME_ENABLED,
    DEFAULT_CHIME_OFFSET,
    DEFAULT_CHIME_VOLUME,
    DEFAULT_COMPRESS_TTS,
    DEFAULT_RESTORE_VOLUME,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_PROMPT,
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
        self._atv_identifier: str | None = None
        self._tts_client: GeminiTTSClient | None = None

        self._attr_unique_id = f"{entry.entry_id}_notify"
        self._attr_name = entry.data.get(CONF_NAME, "HomePod TTS")

    # -- config properties --

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
    def _chime_volume(self) -> float:
        return self._entry.options.get(CONF_CHIME_VOLUME, DEFAULT_CHIME_VOLUME)

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
    def _model(self) -> str:
        return self._entry.options.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL)

    @property
    def _default_prompt(self) -> str:
        return self._entry.options.get(CONF_TTS_PROMPT, DEFAULT_TTS_PROMPT)

    @property
    def _compress_tts(self) -> str:
        return self._entry.options.get(CONF_COMPRESS_TTS, DEFAULT_COMPRESS_TTS)

    @property
    def _chime_offset(self) -> int:
        return self._entry.options.get(CONF_CHIME_OFFSET, DEFAULT_CHIME_OFFSET)

    @property
    def _cache_enabled(self) -> bool:
        return self._entry.options.get(CONF_CACHE_ENABLED, DEFAULT_CACHE_ENABLED)

    @property
    def _cache_max_mb(self) -> int:
        return self._entry.options.get(CONF_CACHE_MAX_MB, DEFAULT_CACHE_MAX_MB)

    # -- TTS client --

    def _get_tts_client(self) -> GeminiTTSClient:
        if (
            self._tts_client is None
            or self._tts_client.voice != self._voice
            or self._tts_client.model != self._model
        ):
            session = async_get_clientsession(self._hass)
            self._tts_client = GeminiTTSClient(
                self._api_key, session, self._voice, self._model
            )
        return self._tts_client

    # -- pyatv connection --

    def _resolve_speaker_identifier(
        self, speaker_entity_id: str | None
    ) -> str:
        """Resolve a media_player entity_id to an apple_tv identifier."""
        if not speaker_entity_id:
            return self._identifier

        # Look up via entity registry to find the config entry
        entity_registry = er.async_get(self._hass)
        entity_entry = entity_registry.async_get(speaker_entity_id)
        if entity_entry and entity_entry.config_entry_id:
            apple_tv_entries = self._hass.config_entries.async_entries(
                "apple_tv"
            )
            for atv_entry in apple_tv_entries:
                if atv_entry.entry_id == entity_entry.config_entry_id:
                    return atv_entry.unique_id or atv_entry.entry_id

        _LOGGER.warning(
            "Could not resolve speaker %s, using default", speaker_entity_id
        )
        return self._identifier

    async def _async_get_connection(
        self, identifier: str | None = None
    ) -> AppleTV:
        target_id = identifier or self._identifier

        # Reuse existing connection if same target
        if self._atv is not None and self._atv_identifier == target_id:
            return self._atv

        # Disconnect from previous if different target
        if self._atv is not None and self._atv_identifier != target_id:
            await self._async_disconnect()

        apple_tv_entries = self._hass.config_entries.async_entries("apple_tv")

        credentials: dict[int, str] = {}
        for atv_entry in apple_tv_entries:
            uid = atv_entry.unique_id or atv_entry.entry_id
            if uid == target_id:
                credentials = atv_entry.data.get("credentials", {})
                break

        atvs = await pyatv.scan(
            self._hass.loop,
            identifier=target_id,
            timeout=5,
        )
        if not atvs:
            raise ConnectionError(
                f"Could not find HomePod with identifier {target_id}"
            )

        conf = atvs[0]
        for protocol_int, cred in credentials.items():
            protocol = pyatv.const.Protocol(int(protocol_int))
            conf.set_credentials(protocol, cred)

        self._atv = await pyatv.connect(conf, self._hass.loop)
        self._atv_identifier = target_id
        return self._atv

    async def _async_disconnect(self) -> None:
        if self._atv is not None:
            self._atv.close()
            self._atv = None
            self._atv_identifier = None

    # -- main TTS pipeline --

    async def async_play_tts(
        self,
        message: str,
        *,
        chime: bool | None = None,
        volume: float | None = None,
        compress: str | None = None,
        offset: int | None = None,
        prompt: str | None = None,
        speaker: str | None = None,
        chime_volume: float | None = None,
    ) -> None:
        if chime is None:
            chime = self._chime_enabled
        if volume is None:
            volume = self._volume
        if compress is None:
            compress = self._compress_tts
        if offset is None:
            offset = self._chime_offset
        if chime_volume is None:
            chime_volume = self._chime_volume

        # Use per-call prompt, fall back to default prompt from options
        effective_prompt = prompt if prompt is not None else self._default_prompt

        # Resolve speaker target
        target_identifier = self._resolve_speaker_identifier(speaker)

        async with self._lock:
            tmp_path = None
            previous_volume: float | None = None
            try:
                tts_client = self._get_tts_client()

                # Check cache
                key = cache_key(
                    message, tts_client.voice, tts_client.model, effective_prompt
                )
                tts_pcm = None
                if self._cache_enabled:
                    tts_pcm = get_cached(self._hass, key)

                if tts_pcm is None:
                    _LOGGER.debug("Synthesizing TTS for: %s", message)
                    tts_pcm = await tts_client.synthesize(
                        message, prompt=effective_prompt or None
                    )
                    if self._cache_enabled:
                        put_cache(self._hass, key, tts_pcm)
                        enforce_max_size(self._hass, self._cache_max_mb)

                fd, tmp_path = tempfile.mkstemp(
                    suffix=".wav", prefix="homepod_tts_"
                )
                os.close(fd)

                chime_path = self._chime_path if chime else None
                await async_generate_wav(
                    self._hass,
                    tts_pcm,
                    chime_path,
                    tmp_path,
                    compress_preset=compress,
                    offset_ms=offset,
                    chime_volume=chime_volume,
                )

                atv = await self._async_get_connection(target_identifier)

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
