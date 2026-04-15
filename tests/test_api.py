from __future__ import annotations

from datetime import UTC, datetime
import unittest

from custom_components.yqt.core.protocol import (
    YQTWatch,
    YQTWatchState,
    build_watch_index,
    build_watch_state,
    compute_sign,
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
            "version": "1.0.1",
        }
        self.assertEqual(
            compute_sign(params),
            "7d9d8b343be1f1a4792631f5a4ff43ec6d3a97b1bf4584ff16e91481113d4069",
        )

    def test_build_watch_index_from_login_metadata(self) -> None:
        payload = {
            "didstr": "0907537528-Eva,3004210780-Cas,",
            "didrole": "0907537528-Dad,3004210780-Dad,",
            "didtype": "0907537528-1,3004210780-1,",
            "isEsim": "0907537528-0,3004210780-0,",
            "total_did_id": "0907537528-134873174,3004210780-63145330,",
            "total_did_model": "0907537528-g36f,3004210780-g36d,",
            "total_did_config": "0907537528-CFG1,3004210780-CFG2,",
        }

        watches = build_watch_index(payload, user_id=34534358)

        self.assertEqual(set(watches), {"0907537528", "3004210780"})
        self.assertEqual(watches["0907537528"].nickname, "Eva")
        self.assertEqual(watches["0907537528"].did_id, "134873174")
        self.assertEqual(watches["3004210780"].model, "g36d")
        self.assertEqual(watches["3004210780"].user_id, 34534358)

    def test_build_watch_state_keeps_previous_on_no_data(self) -> None:
        watch = YQTWatch(
            did="0907537528",
            did_id="134873174",
            model="g36f",
            nickname="Eva",
            rolename="Dad",
        )
        previous = YQTWatchState(
            watch=watch,
            latitude=52.040486,
            longitude=5.1716948,
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


if __name__ == "__main__":
    unittest.main()
