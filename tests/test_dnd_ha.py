"""DND integration checks; run with Home Assistant installed in the test environment."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.yqt import async_setup, async_unload_entry
from custom_components.yqt.const import DOMAIN, SERVICE_SET_DND_SCHEDULE
from custom_components.yqt.core.async_client import YQTApiClient
from custom_components.yqt.core.protocol import YQTError, YQTWatch, YQTWatchState


@unittest.skipUnless(importlib.util.find_spec("homeassistant"), "Home Assistant not installed")
class DndHomeAssistantTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from homeassistant.config_entries import ConfigEntry
        from homeassistant.core import HomeAssistant
        from homeassistant.helpers import frame, device_registry as dr, entity_registry as er, area_registry as ar, label_registry as lr
        from custom_components.yqt.coordinator import YQTDndSettingsCoordinator

        self.config_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.config_dir.cleanup)
        self.hass = HomeAssistant(self.config_dir.name)
        frame.async_setup(self.hass)
        self.addAsyncCleanup(self.hass.async_stop)
        self.watch = YQTWatch("test-watch", "test-id", "", "Test", "Parent", config="DC:2")
        self.client = YQTApiClient(MagicMock(), region="europe", loginname="demo@example.com", password="test")
        self.client.session_id = "test-session"
        self.client._watches = {self.watch.did: self.watch}
        self.main = SimpleNamespace(data={self.watch.did: YQTWatchState(self.watch)})
        self.dnd = YQTDndSettingsCoordinator(self.hass, self.client, self.main)
        self.runtime = {"client": self.client, "coordinator": self.main, "dnd_coordinator": self.dnd}
        self.entry = ConfigEntry(
            domain=DOMAIN, title="Test", version=1, minor_version=1, data={}, options={},
            source="user", unique_id=None, discovery_keys={}, subentries_data=None,
        )
        self.hass.config_entries = MagicMock()
        self.hass.config_entries.async_get_entry.return_value = self.entry
        self.hass.data[DOMAIN] = {self.entry.entry_id: self.runtime}
        self.hass.data[dr.DATA_REGISTRY] = dr.DeviceRegistry(self.hass)
        for module in (dr, er, ar, lr):
            await module.async_load(self.hass, load_empty=True)
        self.registry = dr.async_get(self.hass)
        self.entities = er.async_get(self.hass)
        self.device = self.registry.async_get_or_create(
            config_entry_id=self.entry.entry_id, config_subentry_id=None,
            identifiers={(DOMAIN, self.watch.did)},
        )
        self.entity = self.entities.async_get_or_create(
            "sensor", DOMAIN, "test-dnd", device_id=self.device.id,
            config_entry=self.entry, config_subentry_id=None,
        )
        self.area = ar.async_get(self.hass).async_create("School")
        self.label = lr.async_get(self.hass).async_create("Watches")
        self.registry.async_update_device(self.device.id, area_id=self.area.id, labels={self.label.label_id})
        await async_setup(self.hass, {})

    async def call_action(self, *, target=None, **data):
        from homeassistant.helpers.service import async_call_from_config

        await async_call_from_config(
            self.hass,
            {"action": f"{DOMAIN}.{SERVICE_SET_DND_SCHEDULE}", "target": target if target is not None else {"device_id": self.device.id}, "data": data},
            blocking=True,
        )

    def add_watch(self, did, config):
        watch = YQTWatch(did, f"{did}-id", "", did, "Parent", config=config)
        self.main.data[did] = YQTWatchState(watch)
        self.client._watches[did] = watch
        device = self.registry.async_get_or_create(
            config_entry_id=self.entry.entry_id, config_subentry_id=None, identifiers={(DOMAIN, did)},
        )
        entity = self.entities.async_get_or_create(
            "sensor", DOMAIN, did, device_id=device.id, config_entry=self.entry, config_subentry_id=None,
        )
        self.registry.async_update_device(device.id, area_id=self.area.id, labels={self.label.label_id})
        return device, entity

    async def test_mixed_targets_deduplicate_write_and_refresh(self):
        legacy, _ = self.add_watch("legacy", "DC:1")
        self.add_watch("unknown", "")
        targets = ({"area_id": self.area.id}, {"label_id": self.label.label_id},
                   {"entity_id": "all"}, {"entity_id": self.entity.id},
                   {"device_id": [self.device.id, legacy.id], "entity_id": self.entity.entity_id})
        for target in targets:
            with (
                self.subTest(target=target),
                patch.object(self.client, "_request_json", new=AsyncMock(return_value={"status": 1})) as request,
                patch.object(self.dnd, "async_request_refresh", new_callable=AsyncMock) as refresh,
            ):
                await self.call_action(target=target, periods=["08:00-15:00:mon"])
                request.assert_awaited_once()
                self.assertEqual(request.call_args.kwargs["data"]["did"], self.watch.did)
                self.assertEqual(request.call_args.kwargs["data"]["new_dnd1"], "08:00-15:00-0100000")
                refresh.assert_awaited_once()
        # Registry device targeting also works when no entities exist for it.
        self.entities.async_remove(self.entity.entity_id)
        with (
            patch.object(self.client, "_request_json", new=AsyncMock(return_value={"status": 1})) as request,
            patch.object(self.dnd, "async_request_refresh", new_callable=AsyncMock),
        ):
            await self.call_action(target={"area_id": self.area.id}, periods=[])
            request.assert_awaited_once()
            self.assertTrue(all(request.call_args.kwargs["data"][f"new_dnd{i}_open"] == "1" for i in range(1, 5)))

    async def test_no_supported_target_does_not_write(self):
        from homeassistant.exceptions import HomeAssistantError

        self.watch.config = "DC:1"
        for target in ({}, {"device_id": self.device.id}, {"entity_id": "sensor.missing"},
                       {"entity_id": "none"}, {"area_id": self.area.id}, {"label_id": self.label.label_id}):
            with (
                self.subTest(target=target),
                patch.object(self.client, "_request_json", new_callable=AsyncMock) as request,
                self.assertRaisesRegex(HomeAssistantError, "No YQT Smart watches"),
            ):
                await self.call_action(target=target, periods=[])
            request.assert_not_awaited()

    async def test_action_remains_registered_without_loaded_entries(self):
        from homeassistant.exceptions import HomeAssistantError

        self.main.async_shutdown = MagicMock()
        self.hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        self.assertTrue(await async_unload_entry(self.hass, self.entry))
        self.assertTrue(self.hass.services.has_service(DOMAIN, SERVICE_SET_DND_SCHEDULE))
        # Setup registers the action even before any config entry has loaded.
        self.hass.services.async_remove(DOMAIN, SERVICE_SET_DND_SCHEDULE)
        await async_setup(self.hass, {})
        with patch.object(self.client, "_request_json", new_callable=AsyncMock) as request:
            with self.assertRaisesRegex(HomeAssistantError, "No YQT Smart watches advertising DC:2"):
                await self.call_action(periods=[])
            request.assert_not_awaited()

    async def test_invalid_action_and_failed_write_do_not_refresh(self):
        import voluptuous as vol
        from homeassistant.exceptions import HomeAssistantError

        with (
            patch.object(self.client, "_request_json", new_callable=AsyncMock) as request,
            patch.object(self.dnd, "async_request_refresh", new_callable=AsyncMock) as refresh,
        ):
            for data in ({}, {"periods": None}, {"periods": ""}, {"periods": "08:00-15:00:mon"},
                         {"periods": ["22:00-07:00:mon"]}, {"periods": ["08:00-15:00:mon"] * 5}):
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

    async def test_sensor_exposes_only_enabled_periods_and_keeps_errors_unknown(self):
        from custom_components.yqt.sensor import YQTDndSensor
        from custom_components.yqt.core.protocol import dnd_schedule_fields

        fields = {**dnd_schedule_fields([]), "sosnumber1": "redacted"}
        sensor = YQTDndSensor(self.dnd, self.watch)
        self.assertEqual(sensor.device_info["identifiers"], {(DOMAIN, self.watch.did)})
        for period, flag, expected in (("08:00-15:00-0111110", 1, "off"),
                                       ("08:00-15:00-0111110", 2, "08:00-15:00:mon,tue,wed,thu,fri"),
                                       ("invalid", 2, None)):
            fields.update(new_dnd1=period, new_dnd1_open=flag)
            with patch.object(self.client, "async_find_set_info", new=AsyncMock(return_value={"data": [fields]})):
                self.dnd.data = await self.dnd._async_update_data()
            self.assertNotIn("redacted", repr(self.dnd.data))
            self.assertEqual(sensor.native_value, expected)
            self.assertTrue(sensor.available)
            if expected == "off":
                self.assertEqual(sensor.extra_state_attributes, {"periods": []})
            elif expected:
                self.assertEqual(sensor.extra_state_attributes, {"periods": [{
                    "start": "08:00", "end": "15:00", "weekdays": ["mon", "tue", "wed", "thu", "fri"],
                }]})
            else:
                self.assertEqual(sensor.extra_state_attributes, {})
        self.dnd.data = {}
        self.assertIsNone(sensor.native_value)
        self.assertTrue(sensor.available)

    async def test_poll_skips_legacy_watches_and_isolates_settings_errors(self):
        legacy = YQTWatch("legacy", "legacy-id", "old", "Old", "Parent", config="DC:1")
        self.main.data[legacy.did] = YQTWatchState(legacy)
        with patch.object(self.client, "async_find_set_info", new=AsyncMock(side_effect=YQTError("offline"))) as read:
            self.assertEqual(await self.dnd._async_update_data(), {})
        read.assert_awaited_once_with(self.watch.did)
        self.assertEqual(len(self.main.data), 2)
