from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import ATTR_PERIODS, CONF_LOGINNAME, CONF_PASSWORD, CONF_REGION, DOMAIN, SERVICE_SET_DND_SCHEDULE

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

PLATFORMS = (
    "device_tracker",
    "sensor",
    "button",
    "binary_sensor",
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    import aiohttp

    from homeassistant.helpers.aiohttp_client import async_create_clientsession

    from .core.async_client import YQTApiClient
    from .coordinator import YQTDataUpdateCoordinator, YQTDndSettingsCoordinator

    session = async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
    client = YQTApiClient(
        session,
        region=entry.data[CONF_REGION],
        loginname=entry.data[CONF_LOGINNAME],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = YQTDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    # Settings failures must not block location setup.
    dnd_coordinator = YQTDndSettingsCoordinator(hass, client, coordinator)
    await dnd_coordinator.async_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
        "dnd_coordinator": dnd_coordinator,
    }

    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        runtime = hass.data[DOMAIN].pop(entry.entry_id, None)
        if runtime is not None:
            runtime["coordinator"].async_shutdown()
        if not hass.data[DOMAIN] and hasattr(hass, "services"):
            hass.services.async_remove(DOMAIN, SERVICE_SET_DND_SCHEDULE)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain-level services once, regardless of how many accounts are set up."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_DND_SCHEDULE):
        return

    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv, device_registry as dr

    from .core.protocol import MAX_DND_PERIODS, DndPeriod

    service_schema = vol.Schema(
        {
            vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1)),
            vol.Required(ATTR_PERIODS): vol.All(cv.ensure_list, [cv.string], vol.Length(max=MAX_DND_PERIODS)),
        }
    )

    async def _async_handle_set_dnd_schedule(call: ServiceCall) -> None:
        from homeassistant.exceptions import HomeAssistantError

        from .core.protocol import YQTError

        try:
            periods = [DndPeriod.from_cli_string(value) for value in call.data[ATTR_PERIODS]]
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

        device_registry = dr.async_get(hass)
        for device_id in call.data["device_id"]:
            device = device_registry.async_get(device_id)
            if device is None:
                raise HomeAssistantError(f"unknown device_id: {device_id}")

            did = next((identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN), None)
            if did is None:
                raise HomeAssistantError(f"device {device_id} is not a YQT Smart watch")

            runtime = _find_runtime_for_device(hass, device)
            if runtime is None:
                raise HomeAssistantError(f"no YQT Smart config entry currently owns device {device_id}")

            try:
                await runtime["client"].async_set_dnd_schedule(did, periods)
            except YQTError as exc:
                raise HomeAssistantError(str(exc)) from exc

            await runtime["dnd_coordinator"].async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DND_SCHEDULE,
        _async_handle_set_dnd_schedule,
        schema=service_schema,
    )


def _find_runtime_for_device(hass: HomeAssistant, device: Any) -> dict[str, Any] | None:
    for entry_id, runtime in hass.data.get(DOMAIN, {}).items():
        if entry_id in device.config_entries:
            return runtime
    return None
