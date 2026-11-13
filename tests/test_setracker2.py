from __future__ import annotations

import io
import json
import unittest
from email.message import Message
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from custom_components.yqt.core.protocol import REGIONS, YQTError, YQTResponseError
from custom_components.yqt.core.sync_client import YQTClient
from custom_components.yqt.core.transport import decrypt_response
from yqt_client import SeTracker2Client, _build_parser


class SeTracker2TestCase(unittest.TestCase):
    def setUp(self):
        self.client = SeTracker2Client()

    def test_native_reference_vectors_and_signature_exclusions(self):
        params = {
            "app_flag": "70", "count": "300", "createtime": "2026-11-11 13:38:50",
            "did": "3707897174", "did_id": "157868774", "flag": "3",
            "language": "enUS", "timestamppp": "1794500680652",
        }
        signature = "251998574CF6CB744466F48AE6A0A3119C1E92B031FD9D4072C3CCB32154E0CA"
        self.assertEqual(self.client._sign(params), signature)
        self.assertEqual(self.client._sign(params | {
            "sign": "ignored", "sign_flag": "ignored",
            "encrypted_aes_key": "ignored", "encrypted_aes_iv": "ignored",
        }), signature)
        self.assertNotEqual(self.client._sign(params | {"app_flag": "394"}), signature)
        self.assertEqual(self.client._password_params("alice@example.test", "ExamplePassword!")["newpassword"],
                         "FC3D66F7764F1A9C435F8374D99D32AF27F63AF525F1300A33B29E6D51776EA860")
        self.assertEqual(self.client._aes_encrypt(
            b'{"synthetic":"alice@example.test","app_flag":"70"}',
            self.client.ENVELOPE_KEY, self.client.ENVELOPE_IV,
        ).hex(), "25c7de4cd8e956051147ad52305880f65258b7e7f6af666add22749f0b80cd5a5"
                 "2c7aefc0ef507244980c3fa08b971e2ef13778ff223b9e1fddc70867809b0aa")

    def response(self, payload, *, encrypted=True):
        if encrypted:
            ciphertext = self.client._aes_encrypt(json.dumps(payload).encode(),
                                                  self.client.ENVELOPE_KEY, self.client.ENVELOPE_IV)
            payload = {"encryptIndex": 22, "encryptData": ciphertext.hex()}
        response = MagicMock()
        response.read.return_value = json.dumps(payload).encode()
        response.headers = Message()
        response.headers['Content-Type'] = 'application/json'
        response.__enter__.return_value = response
        return response

    def inner_request(self, request):
        self.assertEqual(request.get_header("X-encrypt-index"), "22")
        self.assertEqual(urlsplit(request.full_url).netloc, "europe.myaqsh.com:9401")
        if request.method == "POST":
            outer = json.loads(request.data)
        else:
            outer = {key: values[0] for key, values in parse_qs(urlsplit(request.full_url).query).items()}
        self.assertEqual(outer["encryptData"], outer["encryptData"].upper())
        return self.client._decrypt_response(outer)

    def test_login_and_session_get_use_setracker_transport_and_cache(self):
        login = {"status": 1, "sid": "test-session", "data": [{"id": 123}],
                 "total_did_id": "123456789-111111111,", "total_did_model": "123456789-model,"}
        with patch.object(self.client.opener, "open", side_effect=[self.response(login), self.response({"status": 1})]) as request:
            self.client.login("alice@example.test", "ExamplePassword!")
            inner = self.inner_request(request.call_args.args[0])
            self.assertEqual(inner["loginname"], "alice@example.test")
            for key, value in {"appid": "aaagg10006", "app_flag": "70", "flag": "70",
                               "version": "3.3.5", "sign_flag": self.client.SIGN_FLAG}.items():
                self.assertEqual(inner[key], value)
            self.assertEqual(inner["sign"], self.client._sign(inner))
            self.assertIn("newpassword", inner)
            self.assertEqual(self.client.session_id, "test-session")
            self.assertEqual(self.client.user_id, 123)
            self.assertEqual(self.client.resolve_device("123456789"), ("123456789", "111111111"))
            self.client.find_last_position(did="test-watch", did_id="test-id")
            wire = request.call_args.args[0]
            self.assertEqual(urlsplit(wire.full_url).path, "/app/test-session/S10APP/v2_findLastPosition")
            self.assertEqual(self.inner_request(wire)["did_id"], "test-id")

    def test_plain_sign_error_and_encrypted_download_error(self):
        with patch.object(self.client.opener, "open", return_value=self.response({"status": -3, "message": "sign error"}, encrypted=False)):
            with self.assertRaises(YQTResponseError) as error:
                self.client.login("alice@example.test", "ExamplePassword!")
            self.assertEqual(error.exception.status, -3)
        with patch.object(self.client.opener, "open", return_value=self.response({"status": 2, "message": "no data"})) as request:
            with self.assertRaises(YQTResponseError) as error:
                self.client._request_bytes("GET", "/test", {"did": "test-watch"})
            self.assertEqual(error.exception.status, 2)
            self.assertEqual(self.inner_request(request.call_args.args[0])["did"], "test-watch")

    def test_malformed_envelopes_and_unverified_credentials_fail_cleanly(self):
        for payload in ({"encryptData": "00"}, {"encryptIndex": 1, "encryptData": "00"},
                        {"encryptIndex": 22, "encryptData": "zz"}, {"encryptIndex": 22, "encryptData": None}):
            with self.subTest(payload=payload), self.assertRaises(YQTError):
                self.client._decrypt_response(payload)
        for password in ("pássword", "password\0"):
            with patch.object(self.client.opener, "open") as request, self.assertRaises(YQTError):
                self.client.login("alice@example.test", password)
            request.assert_not_called()
        with self.assertRaisesRegex(YQTError, "multipart"):
            self.client._request_json_multipart("POST", "/test", {})

    def test_yqt_default_and_region_table_are_unchanged(self):
        self.assertEqual(_build_parser().parse_args(["login"]).protocol, "yqt")
        self.assertEqual(_build_parser().parse_args(["--protocol", "setracker2", "login"]).protocol, "setracker2")
        client = YQTClient()
        self.assertEqual(client.region.base_url, "https://europe.myaqsh.com:11001")
        self.assertEqual(REGIONS['europe'].base_url, client.region.base_url)
        encrypted, index = client._encrypt_request({"loginname": "alice@example.test"}, form_encoded=True)
        self.assertIn(index, range(1, 6))
        self.assertEqual(decrypt_response(encrypted)["loginname"], "alice%40example.test")
        self.assertEqual(set(client._password_params("alice@example.test", "password")), {"password"})

    def test_cli_selects_setracker_and_rejects_multipart_before_login(self):
        import yqt_client
        with patch('sys.argv', ['yqt_client.py', '--protocol', 'setracker2', '--account', 'alice@example.test',
                                '--password', 'test', 'login']), patch.object(yqt_client, 'SeTracker2Client') as client, patch('sys.stdout', new_callable=io.StringIO):
            client.return_value.login.return_value = {"status": 1}
            yqt_client.main()
            client.return_value.login.assert_called_once_with('alice@example.test', 'test')
        with patch('sys.argv', ['yqt_client.py', '--protocol', 'setracker2', 'chat-send', '--did', 'test-watch',
                                '--message', 'test']), patch.object(yqt_client, 'SeTracker2Client') as client, patch('sys.stderr'), self.assertRaises(SystemExit):
            yqt_client.main()
        client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
