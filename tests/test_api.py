from __future__ import annotations

import asyncio
import threading
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import custom_components.yqt as yqt
from custom_components.yqt.const import DOMAIN
from custom_components.yqt.core.async_client import YQTApiClient
from custom_components.yqt.core.protocol import (
    REGIONS,
    YQTResponseError,
    YQTWatch,
    YQTWatchState,
    build_watch_index,
    build_watch_state,
    compute_sign,
    DEFAULT_CLIENT_VERSION,
    is_login_timeout_response,
)
from custom_components.yqt.core.sync_client import YQTClient
from custom_components.yqt.core.transport import (
    CLIENT_CERTIFICATE,
    create_ssl_context,
    decrypt_response,
    encrypt_request,
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

    def test_build_watch_state_uses_corrected_wifi_position(self) -> None:
        current = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "data": [
                    {
                        "datatype": "3",
                        "lat": "50.0",
                        "lng": "5.0",
                        "lat_co": "50.1",
                        "lng_co": "5.1",
                    }
                ],
            },
        )

        self.assertEqual(current.latitude, 50.1)
        self.assertEqual(current.longitude, 5.1)

    def test_build_watch_state_falls_back_from_invalid_wifi_correction(self) -> None:
        current = build_watch_state(
            make_watch(),
            {
                "status": 1,
                "data": [
                    {
                        "datatype": "3",
                        "lat": "50.0",
                        "lng": "5.0",
                        "lat_co": "0",
                        "lng_co": "0",
                    }
                ],
            },
        )

        self.assertEqual(current.latitude, 50.0)
        self.assertEqual(current.longitude, 5.0)

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


class TransportTestCase(unittest.TestCase):
    def test_regions_match_current_apk_endpoints(self) -> None:
        for name, region in REGIONS.items():
            self.assertEqual(region.base_url, f"https://{name}.myaqsh.com:11001")
            self.assertEqual(region.collection_url, f"https://{name}.myaqsh.com:11002")
            self.assertEqual(region.bind_url, f"https://{name}.myaqsh.com:11003")
            self.assertEqual(region.mqtt_url, f"mqtts://{name}.myaqsh.com:8883")

    def test_encrypted_form_round_trip(self) -> None:
        params = {
            "language": "enUS",
            "appid": "aaagg11145",
            "loginname": "demo@example.com",
            "flag": "394",
            "version": DEFAULT_CLIENT_VERSION,
            "isIPHONE": "1",
            "timestamppp": "1776250000000",
            "sign_flag": "KHDIW",
        }

        encrypted, index = encrypt_request(params, form_encoded=True, index=1)
        decrypted = decrypt_response(encrypted)

        self.assertEqual(index, 1)
        self.assertEqual(decrypted["loginname"], "demo%40example.com")
        self.assertEqual(decrypted["app_flag"], "394")
        self.assertEqual(
            decrypted["sign"],
            compute_sign({**params, "app_flag": "394"}),
        )

    def test_decrypts_current_api_response(self) -> None:
        payload = {
            "encryptData": (
                "513b5f9b45cd05077d846ecf2c10644907667617e33c3087903fc2d959947c5a"
                "9fa624a78cb9e0173d0db127fa0a0c0e48347c9fbf44f80af4393820e3c4070"
                "7790baac1ee10920e77fecd3f4d4e86eb043a4ebc2d9328b1170f5de026304bd"
                "d410f77d990a9f1bcd21ab2f74d9833ae81bda511f41a4984b9e3369d76212700"
            ),
            "encryptIndex": 1,
        }

        decrypted = decrypt_response(payload)

        self.assertEqual(decrypted["status"], 2)
        self.assertIn("account is not registered", decrypted["message"])

    def test_client_certificate_loads(self) -> None:
        self.assertTrue(CLIENT_CERTIFICATE.is_file())
        self.assertIsNotNone(create_ssl_context())


class AsyncClientTransportTestCase(unittest.IsolatedAsyncioTestCase):
    def test_command_status_601_is_described_as_offline(self) -> None:
        for client in (YQTApiClient, YQTClient):
            for payload in ({"code": 601}, {"status": 601}):
                with (
                    self.subTest(client=client.__name__, payload=payload),
                    self.assertRaises(YQTResponseError) as raised,
                ):
                    client._ensure_command_success(payload)

                self.assertEqual(raised.exception.status, 601)
                self.assertEqual(
                    raised.exception.message,
                    "Device is offline. Check coverage or settings.",
                )

    async def test_ssl_context_is_created_off_event_loop(self) -> None:
        context = object()
        context_threads: list[int] = []

        def create_context():
            context_threads.append(threading.get_ident())
            return context

        session = MagicMock()
        response = session.request.return_value.__aenter__.return_value
        response.status = 200
        response.text = AsyncMock(return_value='{"status":1}')
        with patch(
            "custom_components.yqt.core.async_client.create_ssl_context",
            new=create_context,
        ):
            client = YQTApiClient(
                session,
                region="europe",
                loginname="demo@example.com",
                password="password",
            )
            self.assertEqual(context_threads, [])
            payload = await client._request_json("GET", "/test", params={})

        self.assertEqual(payload, {"status": 1})
        self.assertEqual(len(context_threads), 1)
        self.assertNotEqual(context_threads[0], threading.get_ident())
        self.assertIs(session.request.call_args.kwargs["ssl"], context)


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
