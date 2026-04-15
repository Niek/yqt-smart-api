from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .core.protocol import YQTError
from .entity import YQTEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(YQTRequestLocationButton(coordinator, did) for did in coordinator.data)


class YQTRequestLocationButton(YQTEntity, ButtonEntity):
    _attr_translation_key = "request_location"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_request_location"

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_request_location(self._did)
        except YQTError as exc:
            raise HomeAssistantError(str(exc)) from exc
