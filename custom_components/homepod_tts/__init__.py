import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

SERVICE_SAY = "say"
ATTR_MESSAGE = "message"
ATTR_ENTITY_ID = "entity_id"
ATTR_CHIME = "chime"
ATTR_VOLUME_LEVEL = "volume_level"
ATTR_COMPRESS = "compress"

SERVICE_SAY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_CHIME): cv.boolean,
        vol.Optional(ATTR_VOLUME_LEVEL): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Optional(ATTR_COMPRESS): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    async def async_handle_say(call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        message = call.data[ATTR_MESSAGE]
        chime = call.data.get(ATTR_CHIME)
        volume = call.data.get(ATTR_VOLUME_LEVEL)
        compress = call.data.get(ATTR_COMPRESS)

        for eid, data in hass.data[DOMAIN].items():
            entity = data.get("entity")
            if entity is not None and entity.entity_id == entity_id:
                await entity.async_play_tts(
                    message, chime=chime, volume=volume, compress=compress
                )
                return

        _LOGGER.error("Entity %s not found in homepod_tts", entity_id)

    if not hass.services.has_service(DOMAIN, SERVICE_SAY):
        hass.services.async_register(
            DOMAIN, SERVICE_SAY, async_handle_say, schema=SERVICE_SAY_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SAY)
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
