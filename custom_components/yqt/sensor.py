from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import YQTDataUpdateCoordinator, YQTDndSettingsCoordinator
from .core.protocol import DndPeriod, supports_dnd_schedule
from .entity import YQTEntity, watch_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    dnd_coordinator = runtime["dnd_coordinator"]
    entities = []
    for did in coordinator.data:
        entities.append(YQTBatterySensor(coordinator, did))
        entities.append(YQTLastFixSensor(coordinator, did))
        entities.append(YQTSpeedSensor(coordinator, did))
        entities.append(YQTWifiAccessPointsSensor(coordinator, did))
        entities.append(YQTCellTowersSensor(coordinator, did))
        if supports_dnd_schedule(coordinator.data[did].watch.config):
            entities.append(YQTDndSensor(dnd_coordinator, coordinator, did))
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


class YQTDndSensor(CoordinatorEntity[YQTDndSettingsCoordinator], SensorEntity):
    """Configured schedule, not the watch's current DND state."""

    _attr_has_entity_name = True
    _attr_translation_key = "dnd_schedule"
    _attr_icon = "mdi:bell-sleep"

    def __init__(
        self,
        dnd_coordinator: YQTDndSettingsCoordinator,
        main_coordinator: YQTDataUpdateCoordinator,
        did: str,
    ) -> None:
        super().__init__(dnd_coordinator)
        self._main_coordinator = main_coordinator
        self._did = did
        self._attr_unique_id = f"{did}_dnd_schedule"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._did in (self.coordinator.data or {})

    @property
    def device_info(self) -> DeviceInfo:
        return watch_device_info(self._main_coordinator.data[self._did].watch)

    @property
    def native_value(self) -> str | None:
        periods = self._periods()
        if periods is None:
            return None
        return "; ".join(str(period) for period in periods if period.enabled) or "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        periods = self._periods()
        if periods is not None:
            attributes["periods"] = [
                {
                    "start": period.start,
                    "end": period.end,
                    "weekdays": period.weekday_names,
                    "enabled": period.enabled,
                }
                for period in periods
            ]
        return attributes

    def _periods(self) -> list[DndPeriod] | None:
        return (self.coordinator.data or {}).get(self._did)
