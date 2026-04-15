from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .protocol import (
    DEFAULT_APP_ID,
    DEFAULT_CLIENT_FLAG,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_IS_IPHONE,
    DEFAULT_LANGUAGE,
    DEFAULT_SIGN_FLAG,
    REGIONS,
    SUCCESS_STATUSES,
    YQTAuthError,
    YQTConnectionError,
    YQTError,
    YQTResponseError,
    YQTWatch,
    YQTWatchState,
    build_watch_index,
    build_watch_state,
    coerce_int,
    compute_sign,
    hash_password,
    is_login_timeout_response,
)


class YQTApiClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        region: str,
        loginname: str,
        password: str,
        language: str = DEFAULT_LANGUAGE,
        request_timeout: float = 20.0,
    ) -> None:
        if region not in REGIONS:
            choices = ", ".join(sorted(REGIONS))
            raise ValueError(f"unknown region {region!r}; choose one of: {choices}")

        self.session = session
        self.region = REGIONS[region]
        self.loginname = loginname
        self.password = password
        self.language = language
        self.request_timeout = request_timeout

        self.session_id: str | None = None
        self.user_id: int | None = None
        self._watches: dict[str, YQTWatch] = {}

    @property
    def watches(self) -> dict[str, YQTWatch]:
        return dict(self._watches)

    async def async_refresh_watch_states(
        self,
        previous: dict[str, YQTWatchState] | None = None,
    ) -> dict[str, YQTWatchState]:
        login_payload = await self.async_login()
        watches = build_watch_index(login_payload, self.user_id)
        if self.user_id is not None:
            device_payload = await self.async_find_device_list_by_user_id()
            device_watches = build_watch_index(device_payload, self.user_id)
            if not watches:
                watches = device_watches
            elif device_watches:
                watches = self._merge_watches(watches, device_watches)

        if not watches:
            raise YQTResponseError(None, "login succeeded but no watches were discovered", login_payload)

        self._watches = watches
        previous = previous or {}
        states: dict[str, YQTWatchState] = {}
        for did, watch in watches.items():
            try:
                response = await self.async_find_last_position(watch)
            except YQTAuthError:
                raise
            except YQTResponseError as exc:
                states[did] = build_watch_state(watch, exc.payload, previous.get(did))
            except YQTError as exc:
                states[did] = build_watch_state(
                    watch,
                    {"status": -1, "message": str(exc), "data": []},
                    previous.get(did),
                )
            else:
                states[did] = build_watch_state(watch, response, previous.get(did))
        return states

    async def async_request_location(self, did: str) -> dict[str, Any]:
        watch = await self._async_ensure_watch(did)
        response = await self._async_send_order(
            f"test?dev_id={watch.did}&com=D3&dev_model={watch.model}",
        )
        if is_login_timeout_response(response):
            await self._async_reauthenticate()
            watch = await self._async_ensure_watch(did)
            response = await self._async_send_order(
                f"test?dev_id={watch.did}&com=D3&dev_model={watch.model}",
            )
        self._ensure_command_success(response)
        return response

    async def async_login(self) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "appid": DEFAULT_APP_ID,
                "password": hash_password(self.password),
                "loginname": self.loginname,
                "flag": DEFAULT_CLIENT_FLAG,
                "version": DEFAULT_CLIENT_VERSION,
                "isIPHONE": DEFAULT_IS_IPHONE,
            }
        )
        response = await self._request_json("POST", "/app/public/S10APP/v2_new_userLogin2", data=payload)
        self._ensure_login_success(response)

        sid = response.get("sid")
        if not isinstance(sid, str) or not sid:
            raise YQTResponseError(None, "login succeeded but no sid was returned", response)

        self.session_id = sid
        users = response.get("data")
        if isinstance(users, list) and users and isinstance(users[0], dict):
            user_id = users[0].get("id")
            if isinstance(user_id, int):
                self.user_id = user_id

        self._watches = build_watch_index(response, self.user_id)
        return response

    async def async_find_device_list_by_user_id(self) -> dict[str, Any]:
        if self.user_id is None:
            raise YQTError("user_id is required before fetching device metadata")

        payload = self._signed_params(
            {
                "language": self.language,
                "user_id": self.user_id,
                "loginname": self.loginname,
            }
        )
        response = await self._request_json("GET", "/app/public/S10APP/v2_findDeviceListByUserId", params=payload)
        self._ensure_status(response, SUCCESS_STATUSES)
        return response

    async def async_find_last_position(self, watch: YQTWatch) -> dict[str, Any]:
        if not watch.did_id:
            raise YQTError(f"did_id is required for watch {watch.did}")

        response = await self._async_find_last_position_once(watch)
        if is_login_timeout_response(response):
            await self._async_reauthenticate()
            refreshed = self._watches.get(watch.did, watch)
            response = await self._async_find_last_position_once(refreshed)
        self._ensure_status(response, SUCCESS_STATUSES | {2})
        response.setdefault("data", [])
        return response

    async def _async_ensure_watch(self, did: str) -> YQTWatch:
        if did not in self._watches or not self.session_id:
            await self.async_login()
        if did not in self._watches and self.user_id is not None:
            device_payload = await self.async_find_device_list_by_user_id()
            self._watches = self._merge_watches(self._watches, build_watch_index(device_payload, self.user_id))

        watch = self._watches.get(did)
        if watch is None:
            raise YQTError(f"unknown watch {did}")
        if not watch.model:
            raise YQTError(f"device model is required for {did}")
        return watch

    async def _async_reauthenticate(self) -> None:
        await self.async_login()
        if self.user_id is None:
            return
        device_payload = await self.async_find_device_list_by_user_id()
        self._watches = self._merge_watches(self._watches, build_watch_index(device_payload, self.user_id))

    async def _async_send_order(self, sendurl: str) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "sid": self.session_id,
                "language": self.language,
                "sendurl": sendurl,
            }
        )
        return await self._request_json("POST", self._session_path("/S10APP/v2_sendOrder"), data=payload)

    async def _async_find_last_position_once(self, watch: YQTWatch) -> dict[str, Any]:
        payload = self._signed_params(
            {
                "language": self.language,
                "did_id": watch.did_id,
                "did": watch.did,
                "id": "",
            }
        )
        return await self._request_json(
            "GET",
            self._session_path("/S10APP/v2_findLastPosition"),
            params=payload,
        )

    @staticmethod
    def _merge_watches(
        primary: dict[str, YQTWatch],
        secondary: dict[str, YQTWatch],
    ) -> dict[str, YQTWatch]:
        merged = dict(primary)
        for did, extra in secondary.items():
            current = merged.get(did)
            if current is None:
                merged[did] = extra
                continue
            merged[did] = YQTWatch(
                did=current.did,
                did_id=current.did_id or extra.did_id,
                model=current.model or extra.model,
                nickname=current.nickname or extra.nickname,
                rolename=current.rolename or extra.rolename,
                user_id=current.user_id if current.user_id is not None else extra.user_id,
                config=current.config or extra.config,
                is_esim=current.is_esim or extra.is_esim,
                watch_type=current.watch_type or extra.watch_type,
            )
        return merged

    def _session_path(self, suffix: str) -> str:
        if not self.session_id:
            raise YQTError("session_id is required; call async_login() first")
        return f"/app/{self.session_id}{suffix}"

    def _signed_params(self, params: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in params.items():
            if value is None:
                continue
            if value == "":
                normalized[key] = ""
                continue
            normalized[key] = str(value)

        normalized.setdefault("timestamppp", str(round(datetime.now(tz=UTC).timestamp() * 1000)))
        normalized.setdefault("sign_flag", DEFAULT_SIGN_FLAG)
        normalized["sign"] = compute_sign(normalized)
        return normalized

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = urljoin(f"{self.region.base_url}/", path.lstrip("/"))

        try:
            async with self.session.request(
                method,
                url,
                params=params,
                data=data,
                headers={"Accept": "application/json"},
                timeout=self.request_timeout,
            ) as response:
                raw = await response.text()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise YQTConnectionError(f"request to {url} failed: {exc}") from exc

        if response.status in {401, 403}:
            raise YQTAuthError(f"HTTP {response.status}: {raw}")
        if response.status >= 400:
            raise YQTConnectionError(f"HTTP {response.status}: {raw}")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise YQTResponseError(None, f"server did not return JSON: {raw[:500]}", {}) from exc

        if not isinstance(payload, dict):
            raise YQTResponseError(None, "server returned a non-object JSON payload", {"payload": payload})
        return payload

    @staticmethod
    def _ensure_status(payload: dict[str, Any], allowed_statuses: set[int]) -> None:
        status = coerce_int(payload.get("status"))
        if status not in allowed_statuses:
            message = str(payload.get("message", "unknown server response"))
            raise YQTResponseError(status, message, payload)

    @staticmethod
    def _ensure_command_success(payload: dict[str, Any]) -> None:
        code = coerce_int(payload.get("code"))
        if code == 200:
            return
        status = coerce_int(payload.get("status"))
        if status in SUCCESS_STATUSES:
            return

        message = str(payload.get("message", payload.get("msg", "unexpected command response")))
        raise YQTResponseError(code if code is not None else status, message, payload)

    @staticmethod
    def _ensure_login_success(payload: dict[str, Any]) -> None:
        status = coerce_int(payload.get("status"))
        if status in SUCCESS_STATUSES:
            return

        message = str(payload.get("message", "unknown login failure"))
        if status == 2:
            raise YQTAuthError(message)
        raise YQTResponseError(status, message, payload)
