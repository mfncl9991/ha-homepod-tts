import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import tts
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CHIME_SOUND_OPTIONS,
    COMPRESS_PRESETS,
    CONF_CACHE_ENABLED,
    CONF_CACHE_MAX_MB,
    CONF_CHIME_ENABLED,
    CONF_CHIME_OFFSET,
    CONF_CHIME_PATH,
    CONF_CHIME_SOUND,
    CONF_CHIME_VOLUME,
    CONF_COMPRESS_TTS,
    CONF_DEFAULT_SPEAKERS,
    CONF_DEFAULT_VOLUME,
    CONF_GEMINI_API_KEY,
    CONF_HA_TTS_LANGUAGE,
    CONF_HA_TTS_VOICE,
    CONF_HOMEPOD_IDENTIFIER,
    CONF_MINI_VOLUME_SCALE,
    CONF_MUTE_ENTITY,
    CONF_QUIET_CHIME_VOLUME,
    CONF_QUIET_ENTITY,
    CONF_QUIET_PROMPT,
    CONF_QUIET_SPEAKERS,
    CONF_QUIET_VOLUME,
    CONF_RESTORE_VOLUME,
    CONF_TTS_ENGINE,
    CONF_TTS_MODEL,
    CONF_TTS_PROMPT,
    CONF_TTS_VOICE,
    DEFAULT_CACHE_ENABLED,
    DEFAULT_CACHE_MAX_MB,
    DEFAULT_CHIME_ENABLED,
    DEFAULT_CHIME_OFFSET,
    DEFAULT_CHIME_SOUND,
    DEFAULT_CHIME_VOLUME,
    DEFAULT_COMPRESS_TTS,
    DEFAULT_MINI_VOLUME_SCALE,
    DEFAULT_QUIET_CHIME_VOLUME,
    DEFAULT_QUIET_PROMPT,
    DEFAULT_QUIET_VOLUME,
    DEFAULT_RESTORE_VOLUME,
    DEFAULT_TTS_ENGINE,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_PROMPT,
    DEFAULT_TTS_VOICE,
    DEFAULT_VOLUME,
    DOMAIN,
    GEMINI_TTS_MODELS,
    GEMINI_VOICES,
    TTS_ENGINE_GEMINI,
)
from .tts_client import GeminiTTSClient

_LOGGER = logging.getLogger(__name__)


def _tts_engine_options(hass) -> list[dict[str, str]]:
    """Build the TTS engine selector options: Gemini + every `tts.*` entity."""
    options = [{"value": TTS_ENGINE_GEMINI, "label": "Gemini (requires API key)"}]
    for state in sorted(hass.states.async_all("tts"), key=lambda s: s.entity_id):
        options.append(
            {
                "value": state.entity_id,
                "label": state.attributes.get("friendly_name", state.entity_id),
            }
        )
    return options


def _ha_tts_language_options(hass, engine: str) -> list[dict[str, str]]:
    """List languages supported by a `tts.*` entity, if it advertises any."""
    instance = tts.get_engine_instance(hass, engine)
    if instance is None:
        return []
    languages = getattr(instance, "supported_languages", None) or []
    return [{"value": lang, "label": lang} for lang in sorted(languages)]


def _ha_tts_voice_options(
    hass, engine: str, language: str | None
) -> list[dict[str, str]]:
    """List voices supported by a `tts.*` entity for a language, if any."""
    instance = tts.get_engine_instance(hass, engine)
    if instance is None:
        return []
    language = language or getattr(instance, "default_language", None)
    if not language:
        return []
    voices = instance.async_get_supported_voices(language) or []
    return [{"value": v.voice_id, "label": v.name} for v in voices]


def _apple_tv_device_options(hass) -> list[dict[str, str]]:
    """Build labeled options for `apple_tv` config entries.

    `apple_tv` config entries are titled after the device's name in Apple's
    ecosystem, which is often just the room (e.g. "Kitchen") — so a HomePod
    and an Apple TV in the same room get identical titles. Disambiguate using
    the associated device's registry name (e.g. "Kitchen HomePod" vs
    "Kitchen Apple TV"), which is where that distinct name actually lives.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    options = []
    for entry in hass.config_entries.async_entries("apple_tv"):
        if not entry.title:
            continue
        label = entry.title
        for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            if entity.entity_id.startswith("media_player."):
                if entity.device_id:
                    device = dev_reg.async_get(entity.device_id)
                    if device:
                        label = device.name_by_user or device.name or label
                break
        options.append({"value": entry.unique_id or entry.entry_id, "label": label})
    return options


class HomePodTTSConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "HomePodTTSOptionsFlow":
        return HomePodTTSOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        apple_tv_entries = self.hass.config_entries.async_entries("apple_tv")
        if not apple_tv_entries:
            return self.async_abort(reason="no_apple_tv_entries")

        device_options = _apple_tv_device_options(self.hass)

        if user_input is not None:
            api_key = user_input.get(CONF_GEMINI_API_KEY, "")
            if api_key:
                session = async_get_clientsession(self.hass)
                client = GeminiTTSClient(api_key, session)
                if not await client.validate_api_key():
                    errors[CONF_GEMINI_API_KEY] = "invalid_api_key"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_HOMEPOD_IDENTIFIER])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
                vol.Required(CONF_HOMEPOD_IDENTIFIER): SelectSelector(
                    SelectSelectorConfig(
                        options=device_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_GEMINI_API_KEY, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )


class HomePodTTSOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        options = self.config_entry.options

        if user_input is not None:
            self._engine = user_input[CONF_TTS_ENGINE]
            return await self.async_step_engine_options()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TTS_ENGINE,
                    default=options.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=_tts_engine_options(self.hass),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_engine_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        options = self.config_entry.options
        current_engine = self._engine

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_TTS_ENGINE: current_engine, **user_input},
            )

        # Build apple_tv media_player options for default speakers
        speaker_options = _apple_tv_device_options(self.hass)
        valid_speaker_values = {o["value"] for o in speaker_options}
        # Filter out any stale saved values that don't match current options
        saved_speakers = [
            s
            for s in options.get(CONF_DEFAULT_SPEAKERS, [])
            if s in valid_speaker_values
        ]

        compress_options = [
            {"value": k, "label": k.capitalize()} for k in COMPRESS_PRESETS
        ]

        # Gemini-specific vs. generic-HA-TTS-specific fields are mutually
        # exclusive — only show the ones relevant to the engine selected on
        # the previous step.
        engine_fields: dict[Any, Any] = {}
        if current_engine == TTS_ENGINE_GEMINI:
            engine_fields[
                vol.Optional(
                    CONF_TTS_MODEL,
                    default=options.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=GEMINI_TTS_MODELS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            engine_fields[
                vol.Optional(
                    CONF_TTS_VOICE,
                    default=options.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=GEMINI_VOICES,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            engine_fields[
                vol.Optional(
                    CONF_TTS_PROMPT,
                    description={
                        "suggested_value": options.get(
                            CONF_TTS_PROMPT, DEFAULT_TTS_PROMPT
                        )
                    },
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        else:
            saved_language = options.get(CONF_HA_TTS_LANGUAGE, "")
            language_options = _ha_tts_language_options(self.hass, current_engine)
            voice_options = _ha_tts_voice_options(
                self.hass, current_engine, saved_language or None
            )

            if language_options:
                engine_fields[
                    vol.Optional(
                        CONF_HA_TTS_LANGUAGE,
                        description={"suggested_value": saved_language},
                    )
                ] = SelectSelector(
                    SelectSelectorConfig(
                        options=language_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                )
            else:
                engine_fields[
                    vol.Optional(
                        CONF_HA_TTS_LANGUAGE,
                        description={"suggested_value": saved_language},
                    )
                ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))

            # Many HA TTS engines (e.g. edge_tts) don't expose a separate
            # voice list — their "language" options already include
            # voice-specific entries. Only show a Voice field when the
            # engine actually has a distinct voice list to offer.
            if voice_options:
                engine_fields[
                    vol.Optional(
                        CONF_HA_TTS_VOICE,
                        description={
                            "suggested_value": options.get(CONF_HA_TTS_VOICE, "")
                        },
                    )
                ] = SelectSelector(
                    SelectSelectorConfig(
                        options=voice_options,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                    )
                )

        schema = vol.Schema(
            {
                **engine_fields,
                vol.Optional(
                    CONF_CHIME_ENABLED,
                    default=options.get(CONF_CHIME_ENABLED, DEFAULT_CHIME_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_CHIME_SOUND,
                    default=options.get(CONF_CHIME_SOUND, DEFAULT_CHIME_SOUND),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=CHIME_SOUND_OPTIONS,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_CHIME_PATH,
                    description={"suggested_value": options.get(CONF_CHIME_PATH, "")},
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_CHIME_VOLUME,
                    default=options.get(CONF_CHIME_VOLUME, DEFAULT_CHIME_VOLUME),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=2.0,
                        step=0.1,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_CHIME_OFFSET,
                    default=options.get(CONF_CHIME_OFFSET, DEFAULT_CHIME_OFFSET),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=-5000,
                        max=5000,
                        step=100,
                        unit_of_measurement="ms",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_DEFAULT_VOLUME,
                    default=options.get(CONF_DEFAULT_VOLUME, DEFAULT_VOLUME),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_MINI_VOLUME_SCALE,
                    default=options.get(
                        CONF_MINI_VOLUME_SCALE, DEFAULT_MINI_VOLUME_SCALE
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.5,
                        max=2.0,
                        step=0.05,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_RESTORE_VOLUME,
                    default=options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME),
                ): bool,
                vol.Optional(
                    CONF_DEFAULT_SPEAKERS,
                    description={"suggested_value": saved_speakers},
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=speaker_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_COMPRESS_TTS,
                    default=options.get(CONF_COMPRESS_TTS, DEFAULT_COMPRESS_TTS),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=compress_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                # -- Mute --
                vol.Optional(
                    CONF_MUTE_ENTITY,
                    description={"suggested_value": options.get(CONF_MUTE_ENTITY, "")},
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["input_boolean", "binary_sensor", "switch"],
                    )
                ),
                # -- Quiet mode --
                vol.Optional(
                    CONF_QUIET_ENTITY,
                    description={"suggested_value": options.get(CONF_QUIET_ENTITY, "")},
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain=["input_boolean", "binary_sensor", "switch"],
                    )
                ),
                vol.Optional(
                    CONF_QUIET_PROMPT,
                    description={
                        "suggested_value": options.get(
                            CONF_QUIET_PROMPT, DEFAULT_QUIET_PROMPT
                        )
                    },
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_QUIET_CHIME_VOLUME,
                    default=options.get(
                        CONF_QUIET_CHIME_VOLUME, DEFAULT_QUIET_CHIME_VOLUME
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=2.0,
                        step=0.1,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_QUIET_VOLUME,
                    default=options.get(CONF_QUIET_VOLUME, DEFAULT_QUIET_VOLUME),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0.0,
                        max=1.0,
                        step=0.05,
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    CONF_QUIET_SPEAKERS,
                    description={
                        "suggested_value": [
                            s
                            for s in options.get(CONF_QUIET_SPEAKERS, [])
                            if s in valid_speaker_values
                        ]
                    },
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=speaker_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                # -- Cache --
                vol.Optional(
                    CONF_CACHE_ENABLED,
                    default=options.get(CONF_CACHE_ENABLED, DEFAULT_CACHE_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_CACHE_MAX_MB,
                    default=options.get(CONF_CACHE_MAX_MB, DEFAULT_CACHE_MAX_MB),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=2000,
                        step=10,
                        unit_of_measurement="MB",
                        mode=NumberSelectorMode.SLIDER,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="engine_options", data_schema=schema)
