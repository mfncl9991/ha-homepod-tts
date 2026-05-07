import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
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

GEMINI_VOICES = [
    "Aoede", "Charon", "Fenrir", "Kore", "Leda",
    "Orus", "Phoebe", "Zephyr",
]


class HomePodTTSConfigFlow(ConfigFlow, domain=DOMAIN):

    VERSION = 1

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

        device_options = [
            {
                "value": entry.unique_id or entry.entry_id,
                "label": entry.title,
            }
            for entry in apple_tv_entries
        ]

        if user_input is not None:
            api_key = user_input[CONF_GEMINI_API_KEY]
            session = async_get_clientsession(self.hass)
            client = GeminiTTSClient(api_key, session)
            if not await client.validate_api_key():
                errors[CONF_GEMINI_API_KEY] = "invalid_api_key"

            if not errors:
                await self.async_set_unique_id(
                    user_input[CONF_HOMEPOD_IDENTIFIER]
                )
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
                vol.Required(CONF_GEMINI_API_KEY): TextSelector(
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
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHIME_ENABLED,
                    default=options.get(CONF_CHIME_ENABLED, DEFAULT_CHIME_ENABLED),
                ): bool,
                vol.Optional(
                    CONF_CHIME_PATH,
                    description={"suggested_value": options.get(CONF_CHIME_PATH, "")},
                ): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
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
                    CONF_RESTORE_VOLUME,
                    default=options.get(CONF_RESTORE_VOLUME, DEFAULT_RESTORE_VOLUME),
                ): bool,
                vol.Optional(
                    CONF_TTS_VOICE,
                    default=options.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=GEMINI_VOICES,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_COMPRESS_TTS,
                    default=options.get(CONF_COMPRESS_TTS, DEFAULT_COMPRESS_TTS),
                ): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
