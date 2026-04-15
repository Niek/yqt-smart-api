from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONF_LOGINNAME, CONF_PASSWORD, CONF_REGION, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = (
    "device_tracker",
    "sensor",
    "button",
    "binary_sensor",
)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .core.async_client import YQTApiClient
    from .coordinator import YQTDataUpdateCoordinator

    client = YQTApiClient(
        async_get_clientsession(hass),
        region=entry.data[CONF_REGION],
        loginname=entry.data[CONF_LOGINNAME],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = YQTDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
        if runtime is not None:
            runtime["coordinator"].async_shutdown()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
