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
    DISABLED_DND_PERIOD,
    FIND_SET_INFO_PATH_SUFFIX,
    REGIONS,
    UP_NEW_DND_SET_INFO_PATH,
    DndPeriod,
    YQTError,
    extract_dnd_periods,
    YQTResponseError,
    YQTWatch,
    YQTWatchState,
    build_watch_index,
    build_watch_state,
    compute_sign,
    DEFAULT_CLIENT_VERSION,
    is_login_timeout_response,
    supports_dnd_schedule,
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


def dnd_settings(**overrides):
    fields = {}
    for index in range(1, 5):
        fields[f"new_dnd{index}"] = DISABLED_DND_PERIOD
        fields[f"new_dnd{index}_open"] = 1
    return fields | overrides


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


class DndPeriodTestCase(unittest.TestCase):
    """DndPeriod formatting and validation match the APK's schedule editor."""

    def test_capability_requires_exact_dc_2(self) -> None:
        self.assertTrue(supports_dnd_schedule("SOS:1_DC:2_TB:1"))
        for config in ("", "DC:0", "DC:1", "DC:20", "ADC:2", "DC", "DC:invalid"):
            with self.subTest(config=config):
                self.assertFalse(supports_dnd_schedule(config))

    def test_rejects_overnight_equal_and_non_padded_times(self) -> None:
        for start, end in (("22:00", "07:00"), ("08:00", "08:00"), ("8:00", "15:00")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                DndPeriod(start=start, end=end, weekdays=frozenset({1}))

    def test_to_period_string_encodes_weekday_bitmap_sunday_first(self) -> None:
        # Monday-Friday -> "0111110" (Sunday..Saturday, Sunday first).
        monday_to_friday = DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5}))
        self.assertEqual(monday_to_friday.to_period_string(), "08:00-15:00-0111110")
        self.assertEqual(monday_to_friday.open_flag, "2")

        weekend_only = DndPeriod(start="12:00", end="13:00", weekdays=frozenset({0, 6}))
        self.assertEqual(weekend_only.to_period_string(), "12:00-13:00-1000001")

    def test_disabled_period_uses_zeroed_string_and_closed_flag(self) -> None:
        disabled = DndPeriod.disabled()
        self.assertEqual(disabled.to_period_string(), DISABLED_DND_PERIOD)
        self.assertEqual(disabled.open_flag, "1")

    def test_enabled_period_requires_at_least_one_weekday(self) -> None:
        with self.assertRaises(ValueError):
            DndPeriod(start="08:00", end="15:00", weekdays=frozenset())

    def test_rejects_out_of_range_time_and_weekday(self) -> None:
        with self.assertRaises(ValueError):
            DndPeriod(start="25:00", end="15:00", weekdays=frozenset({1}))
        with self.assertRaises(ValueError):
            DndPeriod(start="08:00", end="07:99", weekdays=frozenset({1}))
        with self.assertRaises(ValueError):
            DndPeriod(start="08:00", end="15:00", weekdays=frozenset({7}))

    def test_from_period_string_round_trips_with_to_period_string(self) -> None:
        original = DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5}))
        parsed = DndPeriod.from_period_string(original.to_period_string(), original.open_flag)
        self.assertEqual(parsed, original)

    def test_disabled_flag_preserves_saved_times_and_weekdays(self) -> None:
        parsed = DndPeriod.from_period_string("08:00-15:00-0111110", open_flag="1")
        self.assertFalse(parsed.enabled)
        self.assertEqual(parsed.to_period_string(), "08:00-15:00-0111110")
        self.assertEqual(parsed.weekdays, frozenset({1, 2, 3, 4, 5}))
        self.assertEqual(parsed.open_flag, "1")

    def test_unknown_flags_and_enabled_empty_slots_are_invalid(self) -> None:
        for flag in ("0", "3", "None", ""):
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                DndPeriod.from_period_string("08:00-15:00-0111110", flag)
        with self.assertRaises(ValueError):
            DndPeriod.from_period_string(DISABLED_DND_PERIOD, "2")

    def test_from_period_string_rejects_malformed_period(self) -> None:
        with self.assertRaises(ValueError):
            DndPeriod.from_period_string("not-a-period", open_flag="2")
        with self.assertRaises(ValueError):
            DndPeriod.from_period_string("08:00-15:00-01", open_flag="2")

    def test_from_cli_string_parses_start_end_and_days(self) -> None:
        period = DndPeriod.from_cli_string("08:00-15:00:mon,tue,wed,thu,fri")
        self.assertEqual(
            period,
            DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5})),
        )

    def test_from_cli_string_rejects_malformed_input(self) -> None:
        with self.assertRaises(ValueError):
            DndPeriod.from_cli_string("not-a-period")
        with self.assertRaises(ValueError):
            DndPeriod.from_cli_string("08:00-15:00:mon,notaday")


class ExtractDndPeriodsTestCase(unittest.TestCase):
    """Incomplete or malformed replies must never appear to be an off schedule."""

    def test_apk_list_shape_and_integer_flags(self) -> None:
        fields = dnd_settings(new_dnd1="08:00-15:00-0111110", new_dnd1_open=2)
        periods = extract_dnd_periods({"status": 1, "data": [fields]})
        self.assertEqual(len(periods), 4)
        self.assertTrue(periods[0].enabled)
        self.assertFalse(periods[1].enabled)

    def test_incomplete_schedule_is_unknown(self) -> None:
        for key in ("new_dnd4", "new_dnd1_open"):
            fields = dnd_settings()
            del fields[key]
            with self.subTest(key=key):
                self.assertIsNone(extract_dnd_periods({"data": [fields]}))

    def test_empty_slots_are_a_valid_off_schedule(self) -> None:
        self.assertEqual(extract_dnd_periods({"data": [dnd_settings()]}), [DndPeriod.disabled()] * 4)

    def test_empty_or_invalid_disabled_slots_use_apk_defaults(self) -> None:
        for value in (None, "", "garbage", "00:00-00:00-0111110", DISABLED_DND_PERIOD):
            for flag in (0, "0", 1, None):
                with self.subTest(value=value, flag=flag):
                    fields = dnd_settings(new_dnd1=value, new_dnd1_open=flag)
                    self.assertEqual(extract_dnd_periods({"data": [fields]}), [DndPeriod.disabled()] * 4)

    def test_non_two_read_flags_preserve_valid_disabled_times(self) -> None:
        for flag in (0, 1, 3):
            fields = dnd_settings(new_dnd1="08:00-15:00-0111110", new_dnd1_open=flag)
            period = extract_dnd_periods({"data": [fields]})[0]
            self.assertFalse(period.enabled)
            self.assertEqual(period.to_period_string(), "08:00-15:00-0111110")

    def test_invalid_enabled_defaults_remain_unknown(self) -> None:
        for value in (None, "", DISABLED_DND_PERIOD, "00:00-00:00-0111110"):
            fields = dnd_settings(new_dnd1=value, new_dnd1_open=2)
            with self.subTest(value=value):
                self.assertIsNone(extract_dnd_periods({"data": [fields]}))

    def test_absent_or_invalid_payloads_remain_unknown(self) -> None:
        for payload in (None, [], {}, {"data": []}, {"data": [None]}, {"data": "invalid"}):
            with self.subTest(payload=payload):
                self.assertIsNone(extract_dnd_periods(payload))

    def test_returns_none_when_no_dnd_fields_are_present(self) -> None:
        self.assertIsNone(extract_dnd_periods({"status": 1, "data": {"sos_numbers": []}}))

    def test_parses_fields_nested_under_data_dict(self) -> None:
        payload = {
            "status": 1,
            "data": dnd_settings(**{
                "new_dnd1": "08:00-15:00-0111110",
                "new_dnd1_open": "2",
                "new_dnd2": DISABLED_DND_PERIOD,
                "new_dnd2_open": "1",
            }),
        }
        periods = extract_dnd_periods(payload)
        self.assertEqual(len(periods), 4)
        self.assertEqual(
            periods[0],
            DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5})),
        )
        self.assertEqual(periods[1], DndPeriod.disabled())

    def test_parses_fields_at_top_level_when_data_is_not_a_dict(self) -> None:
        payload = {
            **dnd_settings(),
            "status": 1,
            "data": [],
            "new_dnd1": "12:00-13:00-1000001",
            "new_dnd1_open": "2",
        }
        periods = extract_dnd_periods(payload)
        self.assertEqual(
            periods,
            [DndPeriod(start="12:00", end="13:00", weekdays=frozenset({0, 6}))] + [DndPeriod.disabled()] * 3,
        )

    def test_unparseable_slot_makes_entire_schedule_unknown(self) -> None:
        payload = {
            "data": dnd_settings(**{
                "new_dnd1": "garbage",
                "new_dnd1_open": "2",
                "new_dnd2": "08:00-15:00-0111110",
                "new_dnd2_open": "2",
            }),
        }
        periods = extract_dnd_periods(payload)
        self.assertIsNone(periods)


class DndScheduleClientTestCase(unittest.TestCase):
    """YQTClient.find_set_info / set_dnd_schedule, per GH issue #13 (untested live)."""

    def _client(self) -> YQTClient:
        client = YQTClient(region="europe", session_id="abc123")
        client._device_index["9505445780"] = {"did": "9505445780", "did_id": "165923436", "config": "DC:2"}
        return client

    def test_set_rejects_unsupported_or_unknown_capability_before_sending(self) -> None:
        for config in ("DC:1", "DC:0", ""):
            client = self._client()
            client._device_index["9505445780"]["config"] = config
            with patch.object(client, "_request_json") as request:
                with self.assertRaisesRegex(YQTError, "DC:2"):
                    client.set_dnd_schedule(did="9505445780", periods=[])
                request.assert_not_called()

    def test_write_requires_status_one(self) -> None:
        client = self._client()
        with patch.object(client, "_request_json", return_value={"status": 4}):
            with self.assertRaises(YQTResponseError):
                client.set_dnd_schedule(did="9505445780", periods=[])

    def test_find_set_info_uses_session_scoped_path(self) -> None:
        client = self._client()
        with patch.object(client, "_request_json", return_value={"status": 1, "message": "ok"}) as mocked:
            client.find_set_info(did="9505445780")

        method, path, _params = mocked.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(path, f"/app/abc123{FIND_SET_INFO_PATH_SUFFIX}")

    def test_set_dnd_schedule_posts_to_root_level_endpoint(self) -> None:
        client = self._client()
        periods = [DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5}))]

        with patch.object(client, "_request_json", return_value={"status": 1, "message": "ok"}) as mocked:
            client.set_dnd_schedule(did="9505445780", periods=periods)

        method, path, params = mocked.call_args.args
        self.assertEqual(method, "POST")
        # upNewDndSetInfo is root-level, unlike the "/app/{sid}/S10APP/" calls.
        self.assertEqual(path, UP_NEW_DND_SET_INFO_PATH)
        self.assertEqual(params["sid"], "abc123")
        self.assertEqual(params["did"], "9505445780")
        self.assertEqual(params["did_id"], "165923436")
        self.assertEqual(params["new_dnd1"], "08:00-15:00-0111110")
        self.assertEqual(params["new_dnd1_open"], "2")

    def test_set_dnd_schedule_pads_unused_slots_as_disabled(self) -> None:
        client = self._client()
        periods = [DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1}))]

        with patch.object(client, "_request_json", return_value={"status": 1, "message": "ok"}) as mocked:
            client.set_dnd_schedule(did="9505445780", periods=periods)

        _method, _path, params = mocked.call_args.args
        for index in (2, 3, 4):
            self.assertEqual(params[f"new_dnd{index}"], DISABLED_DND_PERIOD)
            self.assertEqual(params[f"new_dnd{index}_open"], "1")

    def test_set_dnd_schedule_with_no_periods_disables_everything(self) -> None:
        client = self._client()
        with patch.object(client, "_request_json", return_value={"status": 1, "message": "ok"}) as mocked:
            client.set_dnd_schedule(did="9505445780")

        _method, _path, params = mocked.call_args.args
        for index in (1, 2, 3, 4):
            self.assertEqual(params[f"new_dnd{index}"], DISABLED_DND_PERIOD)
            self.assertEqual(params[f"new_dnd{index}_open"], "1")

    def test_set_dnd_schedule_rejects_more_than_four_periods(self) -> None:
        client = self._client()
        periods = [DndPeriod(start="08:00", end="15:00", weekdays=frozenset({day})) for day in range(5)]
        with self.assertRaises(YQTError):
            client.set_dnd_schedule(did="9505445780", periods=periods)

    def test_set_dnd_schedule_requires_a_session(self) -> None:
        client = YQTClient(region="europe")
        client._device_index["9505445780"] = {"did": "9505445780", "did_id": "165923436"}
        with self.assertRaises(YQTError):
            client.set_dnd_schedule(did="9505445780")


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
            for key in ("code", "status"):
                with (
                    self.subTest(client=client.__name__, key=key),
                    self.assertRaisesRegex(
                        YQTResponseError,
                        "status=601: Device is offline",
                    ),
                ):
                    client._ensure_command_success({key: 601})

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


class AsyncDndScheduleClientTestCase(unittest.IsolatedAsyncioTestCase):
    """YQTApiClient.async_set_dnd_schedule, the HA-service counterpart of YQTClient.set_dnd_schedule."""

    def _client(self) -> YQTApiClient:
        client = YQTApiClient(
            MagicMock(),
            region="europe",
            loginname="demo@example.com",
            password="password",
        )
        client.session_id = "abc123"
        client._watches["9505445780"] = YQTWatch(
            did="9505445780", did_id="165923436", model="g36f", nickname="", rolename="", config="DC:2"
        )
        return client

    async def test_settings_read_and_write_do_not_require_a_model(self) -> None:
        client = self._client()
        client._watches["9505445780"].model = ""
        with patch.object(client, "_request_json", new=AsyncMock(return_value={"status": 1})) as request:
            await client.async_find_set_info("9505445780")
            self.assertEqual(request.call_args.args, ("GET", f"/app/abc123{FIND_SET_INFO_PATH_SUFFIX}"))
            self.assertEqual(request.call_args.kwargs["params"]["did_id"], "165923436")
            await client.async_set_dnd_schedule("9505445780", [])
            self.assertEqual(request.call_args.args, ("POST", UP_NEW_DND_SET_INFO_PATH))
            self.assertEqual(request.call_args.kwargs["data"]["did_id"], "165923436")

    async def test_settings_read_retry_does_not_require_a_model(self) -> None:
        client = self._client()

        async def reauthenticate():
            client.session_id = "fresh-session"
            client._watches["9505445780"].model = ""

        with (
            patch.object(client, "_request_json", new=AsyncMock(side_effect=[
                {"status": -1, "message": "login timeout"}, {"status": 1}
            ])) as request,
            patch.object(client, "_async_reauthenticate", side_effect=reauthenticate) as login,
        ):
            await client.async_find_set_info("9505445780")
        login.assert_awaited_once()
        self.assertEqual(request.await_count, 2)
        self.assertEqual(request.call_args.args, ("GET", f"/app/fresh-session{FIND_SET_INFO_PATH_SUFFIX}"))

    async def test_location_requires_a_model_before_initial_send_and_retry(self) -> None:
        for missing_initially in (True, False):
            client = self._client()
            if missing_initially:
                client._watches["9505445780"].model = ""

            async def reauthenticate():
                client._watches["9505445780"].model = ""

            with (
                self.subTest(missing_initially=missing_initially),
                patch.object(client, "_async_send_order", new=AsyncMock(return_value={
                    "status": -1, "message": "login timeout"
                })) as send,
                patch.object(client, "_async_reauthenticate", side_effect=reauthenticate),
            ):
                with self.assertRaisesRegex(YQTError, "device model is required"):
                    await client.async_request_location("9505445780")
                self.assertEqual(send.await_count, 0 if missing_initially else 1)

    async def test_rejects_unsupported_capability_before_sending(self) -> None:
        client = self._client()
        client._watches["9505445780"].config = "DC:1"
        with patch.object(client, "_request_json", new_callable=AsyncMock) as request:
            with self.assertRaisesRegex(YQTError, "DC:2"):
                await client.async_set_dnd_schedule("9505445780", [])
            request.assert_not_awaited()

    async def test_retries_only_expired_session_with_refreshed_credentials(self) -> None:
        client = self._client()

        async def reauthenticate():
            client.session_id = "fresh-session"
            client._watches["9505445780"].model = ""

        with (
            patch.object(client, "_request_json", new=AsyncMock(side_effect=[
                {"status": -1, "message": "login timeout"}, {"status": 1}
            ])) as request,
            patch.object(client, "_async_reauthenticate", side_effect=reauthenticate) as login,
        ):
            await client.async_set_dnd_schedule("9505445780", [])
        login.assert_awaited_once()
        self.assertEqual(request.await_count, 2)
        self.assertEqual(request.call_args.kwargs["data"]["sid"], "fresh-session")

    async def test_rejects_failed_write_without_retry(self) -> None:
        client = self._client()
        with patch.object(client, "_request_json", new=AsyncMock(return_value={"status": 4})) as request:
            with self.assertRaises(YQTResponseError):
                await client.async_set_dnd_schedule("9505445780", [])
        request.assert_awaited_once()

    async def test_posts_to_root_level_endpoint(self) -> None:
        client = self._client()
        periods = [DndPeriod(start="08:00", end="15:00", weekdays=frozenset({1, 2, 3, 4, 5}))]

        with patch.object(client, "_request_json", new=AsyncMock(return_value={"status": 1})) as mocked:
            await client.async_set_dnd_schedule("9505445780", periods)

        method, path = mocked.call_args.args
        params = mocked.call_args.kwargs["data"]
        self.assertEqual(method, "POST")
        self.assertEqual(path, UP_NEW_DND_SET_INFO_PATH)
        self.assertEqual(params["sid"], "abc123")
        self.assertEqual(params["did"], "9505445780")
        self.assertEqual(params["did_id"], "165923436")
        self.assertEqual(params["new_dnd1"], "08:00-15:00-0111110")
        self.assertEqual(params["new_dnd1_open"], "2")
        for index in (2, 3, 4):
            self.assertEqual(params[f"new_dnd{index}"], DISABLED_DND_PERIOD)
            self.assertEqual(params[f"new_dnd{index}_open"], "1")

    async def test_rejects_more_than_four_periods(self) -> None:
        client = self._client()
        periods = [DndPeriod(start="08:00", end="15:00", weekdays=frozenset({day})) for day in range(5)]
        with self.assertRaises(YQTError):
            await client.async_set_dnd_schedule("9505445780", periods)

    async def test_requires_a_session(self) -> None:
        client = self._client()
        client.session_id = None
        with self.assertRaises(YQTError):
            await client.async_set_dnd_schedule("9505445780", [])


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


class DndCliTestCase(unittest.TestCase):
    def test_omitting_action_fails_before_login(self) -> None:
        import yqt_client

        with (
            patch("sys.argv", ["yqt_client.py", "set-dnd", "--did", "test-watch"]),
            patch("sys.stderr"),
            patch.object(yqt_client, "YQTClient") as client,
            self.assertRaises(SystemExit) as error,
        ):
            yqt_client.main()
        self.assertEqual(error.exception.code, 2)
        client.assert_not_called()

    def test_clear_and_period_are_mutually_exclusive(self) -> None:
        from yqt_client import _build_parser

        with patch("sys.stderr"), self.assertRaises(SystemExit):
            _build_parser().parse_args([
                "set-dnd", "--did", "test-watch", "--clear", "--period", "08:00-15:00:mon"
            ])

    def test_explicit_clear_and_periods_parse(self) -> None:
        from yqt_client import _build_parser

        clear = _build_parser().parse_args(["set-dnd", "--did", "test-watch", "--clear"])
        self.assertTrue(clear.clear)
        self.assertEqual(clear.period, [])
        schedule = _build_parser().parse_args([
            "set-dnd", "--did", "test-watch", "--period", "08:00-15:00:mon", "--period", "09:00-12:00:sat"
        ])
        self.assertFalse(schedule.clear)
        self.assertEqual(len(schedule.period), 2)


if __name__ == "__main__":
    unittest.main()
