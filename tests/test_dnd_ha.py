"""DND integration checks; run with Home Assistant installed in the test environment."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.yqt import _async_register_services
from custom_components.yqt.const import DOMAIN, SERVICE_SET_DND_SCHEDULE
from custom_components.yqt.core.async_client import YQTApiClient
from custom_components.yqt.core.protocol import YQTError, YQTWatch, YQTWatchState


@unittest.skipUnless(importlib.util.find_spec("homeassistant"), "Home Assistant not installed")
class DndHomeAssistantTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers import frame
        from custom_components.yqt.coordinator import YQTDndSettingsCoordinator

        self.config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_dir.cleanup)
        self.hass = HomeAssistant(self.config_dir.name)
        frame.async_setup(self.hass)
        self.addAsyncCleanup(self.hass.async_stop)
        self.watch = YQTWatch("test-watch", "test-id", "test-model", "Test", "Parent", config="DC:2")
        self.client = YQTApiClient(MagicMock(), region="europe", loginname="demo@example.com", password="test")
        self.client.session_id = "test-session"
        self.client._watches = {self.watch.did: self.watch}
        self.main = SimpleNamespace(data={self.watch.did: YQTWatchState(self.watch)})
        self.dnd = YQTDndSettingsCoordinator(self.hass, self.client, self.main)
        self.runtime = {"client": self.client, "coordinator": self.main, "dnd_coordinator": self.dnd}
        self.hass.data[DOMAIN] = {"test-entry": self.runtime}
        self.device = SimpleNamespace(identifiers={(DOMAIN, self.watch.did)}, config_entries={"test-entry"})
        self.registry = MagicMock()
        self.registry.async_get.return_value = self.device
        self.registry_patch = patch("homeassistant.helpers.device_registry.async_get", return_value=self.registry)
        self.registry_patch.start()
        self.addCleanup(self.registry_patch.stop)
        _async_register_services(self.hass)

    async def call_action(self, **data):
        from homeassistant.helpers.service import async_call_from_config

        await async_call_from_config(
            self.hass,
            {"action": f"{DOMAIN}.{SERVICE_SET_DND_SCHEDULE}", "target": {"device_id": "a" * 32}, "data": data},
            blocking=True,
        )

    async def test_action_writes_then_refreshes_and_explicitly_clears(self):
        with (
            patch.object(self.client, "_request_json", new=AsyncMock(return_value={"status": 1})) as request,
            patch.object(self.dnd, "async_request_refresh", new_callable=AsyncMock) as refresh,
        ):
            await self.call_action(periods=["08:00-15:00:mon,tue,wed,thu,fri"])
            fields = request.call_args.kwargs["data"]
            self.assertEqual(fields["new_dnd1"], "08:00-15:00-0111110")
            self.assertEqual(fields["new_dnd1_open"], "2")
            self.assertEqual(fields["new_dnd4_open"], "1")
            refresh.assert_awaited_once()
            await self.call_action(periods=[])
            self.assertTrue(all(request.call_args.kwargs["data"][f"new_dnd{i}_open"] == "1" for i in range(1, 5)))

    async def test_invalid_action_and_failed_write_do_not_refresh(self):
        import voluptuous as vol
        from homeassistant.exceptions import HomeAssistantError

        with (
            patch.object(self.client, "_request_json", new_callable=AsyncMock) as request,
            patch.object(self.dnd, "async_request_refresh", new_callable=AsyncMock) as refresh,
        ):
            for data in ({}, {"periods": ["22:00-07:00:mon"]}, {"periods": ["08:00-15:00:mon"] * 5}):
                with self.subTest(data=data), self.assertRaises((vol.Invalid, HomeAssistantError)):
                    await self.call_action(**data)
            request.assert_not_awaited()
            self.watch.config = "DC:1"
            with self.assertRaises(HomeAssistantError):
                await self.call_action(periods=[])
            request.assert_not_awaited()
            self.watch.config = "DC:2"
            request.return_value = {"status": 4}
            with self.assertRaises(HomeAssistantError):
                await self.call_action(periods=[])
            refresh.assert_not_awaited()

    async def test_sensor_exposes_only_dnd_and_keeps_invalid_schedule_unknown(self):
        from custom_components.yqt.sensor import YQTDndSensor

        fields = {"sosnumber1": "redacted", "centernumber": "redacted"}
        for index in range(1, 5):
            fields[f"new_dnd{index}"] = "00:00-00:00-0000000"
            fields[f"new_dnd{index}_open"] = 1
        fields["new_dnd1"] = "08:00-15:00-0111110"
        self.dnd.data = {self.watch.did: {"status": 1, "data": [fields]}}
        sensor = YQTDndSensor(self.dnd, self.main, self.watch.did)
        self.assertEqual(sensor.native_value, "off")
        self.assertEqual(set(sensor.extra_state_attributes), {"periods"})
        self.assertEqual(sensor.extra_state_attributes["periods"][0]["start"], "08:00")
        fields["new_dnd1_open"] = 2
        self.assertIn("08:00-15:00", sensor.native_value)
        fields["new_dnd1"] = "invalid"
        self.assertIsNone(sensor.native_value)
        self.assertEqual(sensor.extra_state_attributes, {})
        self.dnd.data = None
        self.assertFalse(sensor.available)

    async def test_poll_skips_legacy_watches_and_isolates_settings_errors(self):
        legacy = YQTWatch("legacy", "legacy-id", "old", "Old", "Parent", config="DC:1")
        self.main.data[legacy.did] = YQTWatchState(legacy)
        with patch.object(self.client, "async_find_set_info", new=AsyncMock(side_effect=YQTError("offline"))) as read:
            self.assertEqual(await self.dnd._async_update_data(), {})
        read.assert_awaited_once_with(self.watch.did)
        self.assertEqual(len(self.main.data), 2)
