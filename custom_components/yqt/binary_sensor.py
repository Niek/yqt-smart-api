from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOCATION_STALE_AFTER
from .entity import YQTEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(YQTLocationStaleBinarySensor(coordinator, did) for did in coordinator.data)


class YQTLocationStaleBinarySensor(YQTEntity, BinarySensorEntity):
    _attr_translation_key = "location_stale"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_location_stale"

    @property
    def is_on(self) -> bool:
        last_fix = self.snapshot.last_fix
        if last_fix is None:
            return True
        return dt_util.utcnow() - last_fix > LOCATION_STALE_AFTER
