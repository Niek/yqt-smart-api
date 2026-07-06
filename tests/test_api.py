from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
import unittest

import custom_components.yqt as yqt
from custom_components.yqt.const import DOMAIN
from custom_components.yqt.core.protocol import (
    YQTWatch,
    YQTWatchState,
    build_watch_index,
    build_watch_state,
    compute_sign,
    DEFAULT_CLIENT_VERSION,
    is_login_timeout_response,
)

# Test fixtures use mocked/censored data only. Do not add real account, device, or location data.


def make_watch() -> YQTWatch:
    return YQTWatch(
        did="123456789",
        did_id="111111111",
        model="g36f",
        nickname="John",
        rolename="Parent",
    )


class ApiHelpersTestCase(unittest.TestCase):
    def test_compute_sign_matches_known_value(self) -> None:
        params = {
            "appid": "aaagg11145",
            "flag": "394",
            "isIPHONE": "1",
            "language": "enUS",
            "loginname": "demo@example.com",
            "password": "wire-password",
            "sign_flag": "KHDIW",
            "timestamppp": "1776250000000",
            "version": DEFAULT_CLIENT_VERSION,
        }
        self.assertEqual(
            compute_sign(params),
            "f68fdd3258719d75e4eda3a0a1ec838e6f5140fc1f23c8eb7db53f61b2c834f6",
        )

    def test_build_watch_index_from_login_metadata(self) -> None:
        payload = {
            "didstr": "123456789-John,987654321-Doe,",
            "didrole": "123456789-Parent,987654321-Parent,",
            "didtype": "123456789-1,987654321-1,",
            "isEsim": "123456789-0,987654321-0,",
            "total_did_id": "123456789-111111111,987654321-222222222,",
            "total_did_model": "123456789-g36f,987654321-g36d,",
            "total_did_config": "123456789-CFG1,987654321-CFG2,",
        }

        watches = build_watch_index(payload, user_id=34534358)

        self.assertEqual(set(watches), {"123456789", "987654321"})
        self.assertEqual(watches["123456789"].nickname, "John")
        self.assertEqual(watches["123456789"].did_id, "111111111")
        self.assertEqual(watches["987654321"].model, "g36d")
        self.assertEqual(watches["987654321"].user_id, 34534358)

    def test_build_watch_state_keeps_previous_on_no_data(self) -> None:
        watch = make_watch()
        previous = YQTWatchState(
            watch=watch,
            latitude=50.00000,
            longitude=5.00000,
            battery=96,
            last_fix=datetime(2026, 4, 15, 12, 2, 0, tzinfo=UTC),
        )

        current = build_watch_state(
            watch,
            {"status": 2, "message": "query failure", "battery": "0", "data": []},
            previous,
        )

        self.assertEqual(current.latitude, previous.latitude)
        self.assertEqual(current.longitude, previous.longitude)
        self.assertEqual(current.battery, previous.battery)
        self.assertEqual(current.last_poll_status, 2)
        self.assertEqual(current.last_poll_message, "query failure")

    def test_build_watch_state_keeps_previous_on_zero_zero_position(self) -> None:
        watch = make_watch()
        previous = YQTWatchState(
            watch=watch,
            latitude=50.00000,
            longitude=5.00000,
        )

        current = build_watch_state(
            watch,
            {"status": 1, "data": [{"lat": "0.0", "lng": "0.0"}]},
            previous,
        )

        self.assertEqual(current.latitude, previous.latitude)
        self.assertEqual(current.longitude, previous.longitude)

    def test_build_watch_state_keeps_previous_location_metadata_on_zero_zero_position(self) -> None:
        watch = make_watch()
        previous = YQTWatchState(
            watch=watch,
            latitude=50.00000,
            longitude=5.00000,
            wifi_access_points=[
                {
                    "bssid": "XX:XX:XX:XX:XX:XX",
                    "signal_dbm": -37,
                    "ssid": "School",
                }
            ],
            cell_towers=[
                {
                    "mcc": "204",
                    "mnc": "8",
                    "lac": "12345",
                    "cid": "1234567",
                    "rxlev": 155,
                }
            ],
        )

        current = build_watch_state(
            watch,
            {
                "status": 1,
                "data": [
                    {
                        "lat": "0.0",
                        "lng": "0.0",
                        "mcc": "999",
                        "mnc": "1",
                        "tmp_base": [{"cid": "9999999", "lac": "99999", "rxlev": "99"}],
                        "tmp_wifi": ["YY:YY:YY:YY:YY:YY,-20,New"],
                    }
                ],
            },
            previous,
        )

        self.assertEqual(current.wifi_access_points, previous.wifi_access_points)
        self.assertEqual(current.cell_towers, previous.cell_towers)

    def test_build_watch_state_parses_location_metadata(self) -> None:
        current = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "message": "query ok",
                "data": [
                    {
                        "battery": "42",
                        "direction": "0.0",
                        "gpsrang": "12.6",
                        "lat": 50.000000,
                        "lng": 5.0000000,
                        "mcc": "204",
                        "mnc": "8",
                        "positiondate": "2026-06-15 22:22:46",
                        "speed": "0.91",
                        "tmp_base": [
                            {
                                "cid": "1234567",
                                "lac": "12345",
                                "rxlev": "155",
                            }
                        ],
                        "tmp_wifi": [
                            "XX:XX:XX:XX:XX:XX,-37,School WiFi",
                            "YY:YY:YY:YY:YY:YY,-57,",
                            "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ,-72,Guest",
                        ],
                    }
                ],
            },
        )

        self.assertEqual(current.battery, 42)
        self.assertEqual(current.speed, 0.91)
        self.assertEqual(current.direction, 0.0)
        self.assertEqual(current.accuracy, 13)
        self.assertEqual(current.last_fix, datetime(2026, 6, 15, 22, 22, 46, tzinfo=UTC))
        self.assertEqual(
            current.wifi_access_points,
            [
                {
                    "bssid": "XX:XX:XX:XX:XX:XX",
                    "signal_dbm": -37,
                    "ssid": "School WiFi",
                },
                {
                    "bssid": "YY:YY:YY:YY:YY:YY",
                    "signal_dbm": -57,
                    "ssid": "",
                },
                {
                    "bssid": "ZZ:ZZ:ZZ:ZZ:ZZ:ZZ",
                    "signal_dbm": -72,
                    "ssid": "Guest",
                },
            ],
        )
        self.assertEqual(
            current.cell_towers,
            [
                {
                    "mcc": "204",
                    "mnc": "8",
                    "lac": "12345",
                    "cid": "1234567",
                    "rxlev": 155,
                }
            ],
        )

    def test_build_watch_state_skips_malformed_location_metadata(self) -> None:
        current = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "data": [
                    {
                        "lat": "50.0",
                        "lng": "5.0",
                        "mcc": "204",
                        "mnc": "8",
                        "tmp_base": [
                            {"cid": "", "lac": "12345", "rxlev": "155"},
                            {"cid": "1234567", "lac": "", "rxlev": "155"},
                            {"cid": "7654321", "lac": "54321", "rxlev": "bad"},
                            "not a cell",
                        ],
                        "tmp_wifi": [
                            "AA:AA:AA:AA:AA:AA,-40,",
                            "BB:BB:BB:BB:BB:BB,not-rssi,School",
                            "missing-rssi",
                            123,
                        ],
                    }
                ],
            },
        )

        self.assertEqual(
            current.wifi_access_points,
            [
                {
                    "bssid": "AA:AA:AA:AA:AA:AA",
                    "signal_dbm": -40,
                    "ssid": "",
                }
            ],
        )
        self.assertEqual(
            current.cell_towers,
            [
                {
                    "mcc": "204",
                    "mnc": "8",
                    "lac": "54321",
                    "cid": "7654321",
                    "rxlev": None,
                }
            ],
        )

    def test_build_watch_state_handles_missing_and_non_list_location_metadata(self) -> None:
        current = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "data": [
                    {
                        "lat": "50.0",
                        "lng": "5.0",
                        "mcc": "204",
                        "mnc": "8",
                        "tmp_base": "not a list",
                        "tmp_wifi": "not a list",
                    }
                ],
            },
        )

        self.assertEqual(current.wifi_access_points, [])
        self.assertEqual(current.cell_towers, [])

        missing_tmp_base = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "data": [
                    {
                        "lat": "50.0",
                        "lng": "5.0",
                        "mcc": "204",
                        "mnc": "8",
                        "tmp_wifi": [],
                    }
                ],
            },
        )

        self.assertEqual(missing_tmp_base.cell_towers, [])

    def test_is_login_timeout_response_detects_backend_session_expiry(self) -> None:
        self.assertTrue(is_login_timeout_response({"status": 607, "message": "Login timeout,Please login agian!"}))
        self.assertTrue(is_login_timeout_response({"message": "Login timeout"}))
        self.assertFalse(is_login_timeout_response({"status": 1, "message": "OK"}))


class IntegrationUnloadTestCase(unittest.TestCase):
    def test_unload_does_not_close_home_assistant_managed_session(self) -> None:
        class FakeConfigEntries:
            async def async_unload_platforms(self, entry, platforms) -> bool:
                return True

        class FakeCoordinator:
            def __init__(self) -> None:
                self.shutdown_called = False

            def async_shutdown(self) -> None:
                self.shutdown_called = True

        class FakeSession:
            def __init__(self) -> None:
                self.close_called = False

            async def close(self) -> None:
                self.close_called = True

        coordinator = FakeCoordinator()
        session = FakeSession()
        entry = SimpleNamespace(entry_id="entry-1")
        hass = SimpleNamespace(
            config_entries=FakeConfigEntries(),
            data={DOMAIN: {entry.entry_id: {"coordinator": coordinator, "session": session}}},
        )

        unload_ok = asyncio.run(yqt.async_unload_entry(hass, entry))

        self.assertTrue(unload_ok)
        self.assertTrue(coordinator.shutdown_called)
        self.assertFalse(session.close_called)
        self.assertNotIn(entry.entry_id, hass.data[DOMAIN])


if __name__ == "__main__":
    unittest.main()
