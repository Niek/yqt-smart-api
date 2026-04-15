from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import YQTDataUpdateCoordinator


class YQTEntity(CoordinatorEntity[YQTDataUpdateCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: YQTDataUpdateCoordinator, did: str) -> None:
        super().__init__(coordinator)
        self._did = did

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._did in self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        watch = self.snapshot.watch
        return DeviceInfo(
            identifiers={(DOMAIN, watch.did)},
            name=watch.name,
            manufacturer=MANUFACTURER,
            model=watch.model or None,
            serial_number=watch.did,
        )

    @property
    def snapshot(self):
        return self.coordinator.data[self._did]
