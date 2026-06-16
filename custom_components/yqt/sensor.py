from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import YQTEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for did in coordinator.data:
        entities.append(YQTBatterySensor(coordinator, did))
        entities.append(YQTLastFixSensor(coordinator, did))
        entities.append(YQTSpeedSensor(coordinator, did))
        entities.append(YQTWifiAccessPointsSensor(coordinator, did))
        entities.append(YQTCellTowersSensor(coordinator, did))
    async_add_entities(entities)


class YQTBatterySensor(YQTEntity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_battery"

    @property
    def native_value(self) -> int | None:
        return self.snapshot.battery


class YQTLastFixSensor(YQTEntity, SensorEntity):
    _attr_translation_key = "last_fix"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_last_fix"

    @property
    def native_value(self):
        return self.snapshot.last_fix


class YQTSpeedSensor(YQTEntity, SensorEntity):
    _attr_translation_key = "speed"
    _attr_device_class = SensorDeviceClass.SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_speed"

    @property
    def native_value(self) -> float | None:
        return self.snapshot.speed


class YQTWifiAccessPointsSensor(YQTEntity, SensorEntity):
    _attr_translation_key = "wifi_access_points"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_wifi_access_points"

    @property
    def native_value(self) -> int:
        return len(self.snapshot.wifi_access_points)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"access_points": self.snapshot.wifi_access_points}


class YQTCellTowersSensor(YQTEntity, SensorEntity):
    _attr_translation_key = "cell_towers"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, did: str) -> None:
        super().__init__(coordinator, did)
        self._attr_unique_id = f"{did}_cell_towers"

    @property
    def native_value(self) -> int:
        return len(self.snapshot.cell_towers)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return {"cell_towers": self.snapshot.cell_towers}
