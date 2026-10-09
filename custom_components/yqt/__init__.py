from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import ATTR_PERIODS, CONF_LOGINNAME, CONF_PASSWORD, CONF_REGION, DOMAIN, SERVICE_SET_DND_SCHEDULE

# The shared core is also imported by the standalone CLI, without Home Assistant.
try:
    from homeassistant.helpers import config_validation as cv
except ModuleNotFoundError as exc:
    if exc.name != "homeassistant":
        raise
    cv = None

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN) if cv else None

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall

PLATFORMS = (
    "device_tracker",
    "sensor",
    "button",
    "binary_sensor",
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    _async_register_services(hass)
    return True


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


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain-level services once, regardless of how many accounts are set up."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_DND_SCHEDULE):
        return

    import voluptuous as vol
    from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er, target

    from .core.protocol import MAX_DND_PERIODS, DndPeriod, supports_dnd_schedule

    service_schema = vol.Schema(
        {
            **cv.TARGET_SERVICE_FIELDS,
            vol.Required(ATTR_PERIODS): vol.All(list, [cv.string], vol.Length(max=MAX_DND_PERIODS)),
        }
    )

    async def _async_handle_set_dnd_schedule(call: ServiceCall) -> None:
        from homeassistant.exceptions import HomeAssistantError

        from .core.protocol import YQTError

        try:
            periods = [DndPeriod.parse(value) for value in call.data[ATTR_PERIODS]]
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        supported = {
            did: runtime
            for runtime in hass.data.get(DOMAIN, {}).values()
            for did, state in (runtime["coordinator"].data or {}).items()
            if supports_dnd_schedule(state.watch.config)
        }
        selection = target.TargetSelection(call.data)
        selection.entity_ids = (
            set(entity_registry.entities) if "all" in selection.entity_ids
            else set(er.async_validate_entity_ids(entity_registry, selection.entity_ids))
        )
        selected = target.async_extract_referenced_entity_ids(hass, selection)
        device_ids = selected.referenced_devices | {
            entry.device_id
            for entity_id in selected.referenced | selected.indirectly_referenced
            if (entry := entity_registry.async_get(entity_id)) is not None and entry.device_id
        }
        watches = sorted({
            did
            for device_id in device_ids
            if (device := device_registry.async_get(device_id)) is not None
            for domain, did in device.identifiers
            if domain == DOMAIN and did in supported
        })
        if not watches:
            raise HomeAssistantError("No YQT Smart watches advertising DC:2 matched the target")

        for did in watches:
            runtime = supported[did]
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
