from __future__ import annotations

import http.cookiejar
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .protocol import (
    DEFAULT_APP_ID,
    DEFAULT_CLIENT_FLAG,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_IS_IPHONE,
    DEFAULT_LANGUAGE,
    DEFAULT_SIGN_FLAG,
    REGIONS,
    SUCCESS_STATUSES,
    YQTError,
    YQTHTTPError,
    YQTResponseError,
    build_watch_index,
    compute_sign,
    hash_password,
    photo_wall_filename,
    split_dids,
    watches_to_rows,
)


class YQTClient:
    def __init__(
        self,
        *,
        region: str = "europe",
        language: str = DEFAULT_LANGUAGE,
        timeout: float = 20.0,
        app_id: str = DEFAULT_APP_ID,
        client_flag: int = DEFAULT_CLIENT_FLAG,
        client_version: str = DEFAULT_CLIENT_VERSION,
        is_iphone: int = DEFAULT_IS_IPHONE,
        session_id: str | None = None,
    ) -> None:
        if region not in REGIONS:
            choices = ", ".join(sorted(REGIONS))
            raise ValueError(f"unknown region {region!r}; choose one of: {choices}")

        self.region = REGIONS[region]
        self.language = language
        self.timeout = timeout
        self.app_id = app_id
        self.client_flag = client_flag
        self.client_version = client_version
        self.is_iphone = is_iphone
        self.session_id = session_id
        self.loginname: str | None = None
        self.user_id: int | None = None
        self._device_index: dict[str, dict[str, Any]] = {}

        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def login(self, loginname: str, password: str) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "appid": self.app_id,
                "password": hash_password(password),
                "loginname": loginname,
                "flag": self.client_flag,
                "version": self.client_version,
                "isIPHONE": self.is_iphone,
            }
        )
        response = self._request_json("POST", "/app/public/S10APP/v2_new_userLogin2", payload)
        self._ensure_success(response)

        sid = response.get("sid")
        if isinstance(sid, str) and sid:
            self.session_id = sid
        self.loginname = loginname
        users = response.get("data")
        if isinstance(users, list) and users and isinstance(users[0], dict):
            user_id = users[0].get("id")
            if isinstance(user_id, int):
                self.user_id = user_id
        self._cache_device_metadata(response)
        return response

    def find_user_device_info(self, user_id: int | str, loginname: str, *, device_type: int = 0) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "user_id": user_id,
                "loginname": loginname,
                "type": device_type,
            }
        )
        response = self._request_json("GET", "/app/public/S10APP/v2_new_findUserDeviceInfo", payload)
        self._ensure_success(response)
        data = response.get("data")
        if isinstance(data, list):
            self._cache_device_rows(data)
        return response

    def find_device_list_by_user_id(self, user_id: int | str, loginname: str) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "user_id": user_id,
                "loginname": loginname,
            }
        )
        response = self._request_json("GET", "/app/public/S10APP/v2_findDeviceListByUserId", payload)
        self._ensure_success(response)
        self._cache_device_metadata(response)
        return response

    def find_user_device_by_did(self, *, did: str, did_id: str = "") -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "did": did,
                "did_id": did_id,
            }
        )
        response = self._request_json("GET", "/app/public/S10APP/v2_new_findUserDeviceByDid", payload)
        self._ensure_success(response)
        return response

    def list_devices(self, user_id: int | str, loginname: str, *, device_type: int = 1) -> dict[str, Any]:
        try:
            response = self.find_user_device_info(user_id, loginname, device_type=device_type)
            data = response.get("data")
            if isinstance(data, list) and data:
                return response
        except YQTResponseError as exc:
            if exc.status != 2:
                raise

        if isinstance(user_id, int):
            self.user_id = user_id

        meta = self.find_device_list_by_user_id(user_id, loginname)
        devices = watches_to_rows(build_watch_index(meta, self.user_id))
        for device in devices:
            did = str(device["did"])
            try:
                detail = self.find_user_device_by_did(did=did, did_id=str(device.get("did_id", "")))
            except YQTError:
                detail = {}
            detail_rows = detail.get("data") if isinstance(detail, dict) else None
            if isinstance(detail_rows, list) and detail_rows:
                device.update(detail_rows[0])

        self._cache_device_rows(devices)

        return {
            "status": 1,
            "message": "query ok",
            "source": "meta_fallback",
            "data": devices,
            "didstr": meta.get("didstr"),
            "didrole": meta.get("didrole"),
            "didtype": meta.get("didtype"),
            "isEsim": meta.get("isEsim"),
            "total_did_id": meta.get("total_did_id"),
            "total_did_model": meta.get("total_did_model"),
            "total_did_config": meta.get("total_did_config"),
        }

    def send_order(self, *, sendurl: str, sid: str | None = None) -> dict[str, Any]:
        session = sid or self.session_id
        path = self._session_path(session, "/S10APP/v2_sendOrder")
        payload = self._signed_params(
            {
                "sid": session,
                "language": self.language,
                "sendurl": sendurl,
            }
        )
        response = self._request_json("POST", path, payload)
        self._ensure_command_success(response)
        return response

    def fresh_position(self, *, did: str, model: str = "", sid: str | None = None) -> dict[str, Any]:
        model = self.resolve_device_model(did, model)
        return self.send_order(sendurl=f"test?dev_id={did}&com=D3&dev_model={model}", sid=sid)

    def find_last_position(
        self,
        *,
        did: str,
        did_id: str = "",
        position_id: str = "",
        sid: str | None = None,
    ) -> dict[str, Any]:
        did, did_id = self.resolve_device(did, did_id)
        path = self._session_path(sid, "/S10APP/v2_findLastPosition")
        payload = self._signed_params(
            {
                "language": self.language,
                "did_id": did_id,
                "did": did,
                "id": position_id,
            }
        )
        response = self._request_json("GET", path, payload)
        self._ensure_status(response, SUCCESS_STATUSES | {2})
        response.setdefault("data", [])
        return response

    def find_photo_wall_info(self, *, did: str, max_id: int = 0, sid: str | None = None) -> dict[str, Any]:
        path = self._session_path(sid, "/S10APP/v2_findPictrueDoorInfo")
        payload = self._signed_params(
            {
                "language": self.language,
                "did": did,
                "max_id": max_id,
            }
        )
        response = self._request_json("GET", path, payload)
        self._ensure_success(response)
        response.setdefault("data", [])
        return response

    def download_photo_wall(self, *, did: str, filename: str, sid: str | None = None) -> bytes:
        normalized_filename = photo_wall_filename(filename)
        if not normalized_filename:
            raise YQTError("filename is required")
        path = self._session_path(sid, "/S10APP/v2_downloadPictrueDoor")
        payload = self._signed_params(
            {
                "did": did,
                "filename": normalized_filename,
            }
        )
        return self._request_bytes("GET", path, payload, accept="image/jpeg")

    def find_talk_new_info(
        self,
        *,
        did: str,
        did_id: str = "",
        user_id: int | None = None,
        create_time: str = "",
        sid: str | None = None,
    ) -> dict[str, Any]:
        did, did_id = self.resolve_device(did, did_id)
        resolved_user_id = self.resolve_user_id(user_id)
        path = self._session_path(sid, "/S10APP/findTalkNewInfo")
        payload = self._signed_params(
            {
                "language": self.language,
                "user_id": resolved_user_id,
                "did_id": did_id,
                "did": did,
                "create_time": create_time,
            }
        )
        response = self._request_json("POST", path, payload)
        self._ensure_status(response, SUCCESS_STATUSES | {2})
        response.setdefault("data", [])
        return response

    def send_talk_message(
        self,
        *,
        did: str,
        message: str,
        did_id: str = "",
        user_id: int | None = None,
        loginname: str | None = None,
        file_type: int = 3,
        flag: int = 1,
        sid: str | None = None,
    ) -> dict[str, Any]:
        if not message:
            raise YQTError("message is required")

        did, did_id = self.resolve_device(did, did_id)
        resolved_user_id = self.resolve_user_id(user_id)
        resolved_loginname = self.resolve_loginname(loginname)
        path = self._session_path(sid, "/S10APP/addTalkNewInfo")
        payload = self._signed_params(
            {
                "language": self.language,
                "did_id": did_id,
                "did": did,
                "user_id": resolved_user_id,
                "loginname": resolved_loginname,
                "file_type": file_type,
                "flag": flag,
                "app_flag": self.client_flag,
                "message": message,
            }
        )
        response = self._request_json_multipart("POST", path, payload)
        self._ensure_success(response)
        return response

    def find_last_position_by_more(
        self,
        *,
        loginname: str,
        dids: str,
        did: str = "",
        position_id: str = "",
        sid: str | None = None,
    ) -> dict[str, Any]:
        did_list = split_dids(dids)
        if not did:
            if not did_list:
                raise YQTError("dids must include at least one device id")
            did = did_list[0]
        path = self._session_path(sid, "/S10APP/v2_findLastPositionByMore")
        payload_params: dict[str, Any] = {
            "language": self.language,
            "loginname": loginname,
            "dids": ",".join(did_list),
            "did": did,
        }
        if position_id:
            payload_params["id"] = position_id
        payload = self._signed_params(payload_params)
        response = self._request_json("GET", path, payload)
        self._ensure_success(response)
        return response

    def find_last_positions(self, dids: list[str], *, position_id: str = "") -> dict[str, Any]:
        data: list[dict[str, Any]] = []
        for did in dids:
            response = self.find_last_position(did=did, position_id=position_id)
            device = dict(self._device_index.get(did, {"did": did}))
            rows = response.get("data")
            if isinstance(rows, list) and rows:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    entry = dict(device)
                    entry.update(row)
                    data.append(entry)
                continue

            entry = dict(device)
            entry["message"] = response.get("message", "")
            entry["status"] = response.get("status")
            data.append(entry)

        return {
            "status": 1,
            "message": "query ok",
            "data": data,
        }

    def find_alarm_info(
        self,
        *,
        did: str,
        did_id: str = "",
        flag: int = 0,
        count: int = 20,
        createtime: str = "",
        sid: str | None = None,
    ) -> dict[str, Any]:
        did, did_id = self.resolve_device(did, did_id)
        path = self._session_path(sid, "/S10APP/v2_findAlarmInfo")
        payload = self._signed_params(
            {
                "language": self.language,
                "did": did,
                "did_id": did_id,
                "flag": flag,
                "count": count,
                "createtime": createtime,
            }
        )
        response = self._request_json("GET", path, payload)
        self._ensure_status(response, SUCCESS_STATUSES | {2})
        response.setdefault("data", [])
        return response

    def find_device_switch(self, *, did: str, did_id: str = "", sid: str | None = None) -> dict[str, Any]:
        did, did_id = self.resolve_device(did, did_id)
        path = self._session_path(sid, "/S10APP/v2_findDeviceSwitch")
        payload = self._signed_params(
            {
                "did_id": did_id,
                "did": did,
                "language": self.language,
            }
        )
        response = self._request_json("GET", path, payload)
        self._ensure_success(response)
        return response

    def signed_get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self._request_json("GET", path, self._signed_params(params))
        self._ensure_success(response)
        return response

    def signed_post(self, path: str, **params: Any) -> dict[str, Any]:
        response = self._request_json("POST", path, self._signed_params(params))
        self._ensure_success(response)
        return response

    def resolve_device(self, did: str, did_id: str = "") -> tuple[str, str]:
        if did_id:
            device = self._device_index.get(did, {})
            if device:
                device["did_id"] = did_id
            else:
                self._device_index[did] = {"did": did, "did_id": did_id}
            return did, did_id

        device = self._device_index.get(did)
        if device and isinstance(device.get("did_id"), str) and device["did_id"]:
            return did, device["did_id"]

        raise YQTError(
            f"did_id is required for device {did}; log in with --loginname/--password first or pass --did-id explicitly"
        )

    def resolve_device_model(self, did: str, model: str = "") -> str:
        if model:
            cached = self._device_index.setdefault(did, {"did": did})
            cached["model"] = model
            return model

        device = self._device_index.get(did)
        if device:
            for key in ("model", "dev_model"):
                value = device.get(key)
                if isinstance(value, str) and value:
                    return value

        raise YQTError(
            f"device model is required for {did}; log in with --loginname/--password first or pass --model explicitly"
        )

    def resolve_user_id(self, user_id: int | None = None) -> int:
        if user_id is not None:
            self.user_id = user_id
            return user_id
        if isinstance(self.user_id, int):
            return self.user_id
        raise YQTError("user_id is required; log in with --loginname/--password first or pass --user-id explicitly")

    def resolve_loginname(self, loginname: str | None = None) -> str:
        if loginname:
            self.loginname = loginname
            return loginname
        if isinstance(self.loginname, str) and self.loginname:
            return self.loginname
        raise YQTError("loginname is required; log in with --loginname/--password first or pass --loginname explicitly")

    def known_dids(self) -> list[str]:
        return list(self._device_index)

    def _cache_device_metadata(self, payload: dict[str, Any]) -> None:
        self._cache_device_rows(watches_to_rows(build_watch_index(payload, self.user_id)))

    def _cache_device_rows(self, devices: list[dict[str, Any]]) -> None:
        for device in devices:
            did = device.get("did")
            if not isinstance(did, str) or not did:
                continue
            cached = self._device_index.setdefault(did, {"did": did})
            for key, value in device.items():
                if value in (None, "") and key in cached:
                    continue
                cached[key] = value

    def _session_path(self, sid: str | None, suffix: str) -> str:
        session = sid or self.session_id
        if not session:
            raise YQTError("session_id is required; call login() first or pass sid= explicitly")
        return f"/app/{session}{suffix}"

    def _signed_params(self, params: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if value == "":
                normalized[key] = ""
                continue
            normalized[key] = str(value)

        normalized.setdefault("timestamppp", str(int(time.time() * 1000)))
        normalized.setdefault("sign_flag", DEFAULT_SIGN_FLAG)
        normalized["sign"] = compute_sign(normalized)
        return normalized

    def _request_json(self, method: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        url = urllib.parse.urljoin(f"{self.region.base_url}/", path.lstrip("/"))
        headers = {"Accept": "application/json"}

        if method == "GET":
            query = urllib.parse.urlencode(params)
            request = urllib.request.Request(f"{url}?{query}", headers=headers, method="GET")
        elif method == "POST":
            body = urllib.parse.urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        else:
            raise ValueError(f"unsupported method {method!r}")

        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise YQTHTTPError(exc.code, body) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YQTError(f"server did not return JSON: {raw[:500]}") from exc

    def _request_json_multipart(
        self,
        method: str,
        path: str,
        params: dict[str, str],
        *,
        file_field: str | None = None,
        file_path: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        if method != "POST":
            raise ValueError(f"unsupported multipart method {method!r}")

        boundary = f"----YQTBoundary{int(time.time() * 1000)}"
        body = bytearray()

        for key, value in params.items():
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("ascii"))
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        if file_field and file_path:
            payload_path = Path(file_path)
            detected_type = content_type or mimetypes.guess_type(payload_path.name)[0] or "application/octet-stream"
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(
                (
                    f'Content-Disposition: form-data; name="{file_field}"; '
                    f'filename="{payload_path.name}"\r\n'
                ).encode("utf-8")
            )
            body.extend(f"Content-Type: {detected_type}\r\n\r\n".encode("ascii"))
            body.extend(payload_path.read_bytes())
            body.extend(b"\r\n")

        body.extend(f"--{boundary}--\r\n".encode("ascii"))

        url = urllib.parse.urljoin(f"{self.region.base_url}/", path.lstrip("/"))
        headers = {
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        request = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")

        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise YQTHTTPError(exc.code, body) from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YQTError(f"server did not return JSON: {raw[:500]}") from exc

    def _request_bytes(self, method: str, path: str, params: dict[str, str], *, accept: str = "*/*") -> bytes:
        url = urllib.parse.urljoin(f"{self.region.base_url}/", path.lstrip("/"))
        headers = {"Accept": accept}

        if method == "GET":
            query = urllib.parse.urlencode(params)
            request = urllib.request.Request(f"{url}?{query}", headers=headers, method="GET")
        elif method == "POST":
            body = urllib.parse.urlencode(params).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        else:
            raise ValueError(f"unsupported method {method!r}")

        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                content_type = response.headers.get_content_type()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise YQTHTTPError(exc.code, body) from exc

        if content_type == "application/json" or raw.lstrip().startswith((b"{", b"[")):
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                return raw
            if isinstance(payload, dict):
                status = payload.get("status")
                code = payload.get("code")
                message = str(payload.get("message", payload.get("msg", "unexpected JSON response")))
                if isinstance(status, int):
                    raise YQTResponseError(status, message, payload)
                if isinstance(code, int):
                    raise YQTResponseError(code, message, payload)
            raise YQTError(f"server returned JSON instead of raw bytes: {payload}")

        return raw

    @staticmethod
    def _ensure_success(payload: dict[str, Any]) -> None:
        YQTClient._ensure_status(payload, SUCCESS_STATUSES)

    @staticmethod
    def _ensure_command_success(payload: dict[str, Any]) -> None:
        code = payload.get("code")
        if code == 200:
            return
        if isinstance(payload.get("status"), int):
            YQTClient._ensure_success(payload)
            return
        message = str(payload.get("message", payload.get("msg", "unknown command response")))
        raise YQTResponseError(code if isinstance(code, int) else None, message, payload)

    @staticmethod
    def _ensure_status(payload: dict[str, Any], allowed_statuses: set[int]) -> None:
        status = payload.get("status")
        if status not in allowed_statuses:
            message = str(payload.get("message", "unknown server response"))
            raise YQTResponseError(status if isinstance(status, int) else None, message, payload)
