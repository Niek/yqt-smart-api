from __future__ import annotations

import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, POLL_INTERVAL, REQUEST_LOCATION_REFRESH_DELAY
from .core.async_client import YQTApiClient
from .core.protocol import YQTAuthError, YQTError, YQTWatchState

_LOGGER = logging.getLogger(__name__)


class YQTDataUpdateCoordinator(DataUpdateCoordinator[dict[str, YQTWatchState]]):
    def __init__(self, hass: HomeAssistant, client: YQTApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self.client = client
        self._delayed_refresh_unsub: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> dict[str, YQTWatchState]:
        try:
            return await self.client.async_refresh_watch_states(self.data)
        except YQTAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except YQTError as exc:
            raise UpdateFailed(str(exc)) from exc

    async def async_request_location(self, did: str) -> None:
        try:
            await self.client.async_request_location(did)
        except YQTAuthError as exc:
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except YQTError as exc:
            raise UpdateFailed(str(exc)) from exc

        self._async_schedule_delayed_refresh()

    @callback
    def async_shutdown(self) -> None:
        if self._delayed_refresh_unsub is not None:
            self._delayed_refresh_unsub()
            self._delayed_refresh_unsub = None

    @callback
    def _async_schedule_delayed_refresh(self) -> None:
        if self._delayed_refresh_unsub is not None:
            return

        self._delayed_refresh_unsub = async_call_later(
            self.hass,
            REQUEST_LOCATION_REFRESH_DELAY,
            self._async_handle_delayed_refresh,
        )

    async def _async_handle_delayed_refresh(self, _now) -> None:
        self._delayed_refresh_unsub = None
        await self.async_request_refresh()
