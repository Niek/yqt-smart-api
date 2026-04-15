from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any


DEFAULT_REGION = "europe"
DEFAULT_LANGUAGE = "enUS"
DEFAULT_APP_ID = "aaagg11145"
DEFAULT_CLIENT_FLAG = 394
DEFAULT_CLIENT_VERSION = "1.0.1"
DEFAULT_IS_IPHONE = 1
DEFAULT_SIGN_FLAG = "KHDIW"
SIGN_PREFIX = "SECRPRO"
SUCCESS_STATUSES = {1, 4}
DEVICE_META_KEYS = (
    "didstr",
    "didrole",
    "didtype",
    "isEsim",
    "total_did_id",
    "total_did_model",
    "total_did_config",
)


@dataclass(frozen=True, slots=True)
class RegionConfig:
    name: str
    base_url: str
    collection_url: str
    bind_url: str
    mqtt_url: str


REGIONS: dict[str, RegionConfig] = {
    "europe": RegionConfig(
        name="europe",
        base_url="https://europe.myaqsh.com:8093",
        collection_url="https://europe.myaqsh.com:8082",
        bind_url="https://europe.myaqsh.com:8084",
        mqtt_url="tcp://52.28.132.157:1883",
    ),
    "asia": RegionConfig(
        name="asia",
        base_url="https://asia.myaqsh.com:8093",
        collection_url="https://asia.myaqsh.com:8082",
        bind_url="https://asia.myaqsh.com:8084",
        mqtt_url="tcp://54.169.10.136:1883",
    ),
    "northam": RegionConfig(
        name="northam",
        base_url="https://northam.myaqsh.com:8093",
        collection_url="https://northam.myaqsh.com:8082",
        bind_url="https://northam.myaqsh.com:8084",
        mqtt_url="tcp://54.153.6.9:1883",
    ),
    "southam": RegionConfig(
        name="southam",
        base_url="https://southam.myaqsh.com:8093",
        collection_url="https://southam.myaqsh.com:8082",
        bind_url="https://southam.myaqsh.com:8084",
        mqtt_url="tcp://54.207.93.14:1883",
    ),
    "hk": RegionConfig(
        name="hk",
        base_url="https://hk.myaqsh.com:8093",
        collection_url="https://hk.myaqsh.com:8082",
        bind_url="https://hk.myaqsh.com:8084",
        mqtt_url="tcp://47.91.138.192:1883",
    ),
    "vie": RegionConfig(
        name="vie",
        base_url="https://vie.myaqsh.com:8093",
        collection_url="https://vie.myaqsh.com:8082",
        bind_url="https://vie.myaqsh.com:8083",
        mqtt_url="tcp://103.7.40.198:1883",
    ),
    "russ": RegionConfig(
        name="russ",
        base_url="https://russ.myaqsh.com:8093",
        collection_url="https://russ.myaqsh.com:8082",
        bind_url="https://russ.myaqsh.com:8083",
        mqtt_url="tcp://156.229.16.166:1883",
    ),
}


class YQTError(RuntimeError):
    """Base YQT API error."""


class YQTConnectionError(YQTError):
    """Transport or HTTP-level failure."""


class YQTAuthError(YQTError):
    """Authentication failure."""


class YQTHTTPError(YQTError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class YQTResponseError(YQTError):
    """API returned an unexpected payload."""

    def __init__(self, status: int | None, message: str, payload: dict[str, Any]) -> None:
        label = f"status={status}" if status is not None else "missing status"
        super().__init__(f"{label}: {message}")
        self.status = status
        self.message = message
        self.payload = payload


@dataclass(slots=True)
class YQTWatch:
    did: str
    did_id: str
    model: str
    nickname: str
    rolename: str
    user_id: int | None = None
    config: str = ""
    is_esim: str = ""
    watch_type: str = ""

    @property
    def name(self) -> str:
        return self.nickname or self.did


@dataclass(slots=True)
class YQTWatchState:
    watch: YQTWatch
    latitude: float | None = None
    longitude: float | None = None
    battery: int | None = None
    last_fix: datetime | None = None
    address: str | None = None
    speed: float | None = None
    direction: float | None = None
    accuracy: int | None = None
    raw_position: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    last_poll_status: int | None = None
    last_poll_message: str = ""


def _md5_hex(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return _sha256_hex(_md5_hex(password))


def compute_sign(params: dict[str, Any]) -> str:
    filtered = {key: str(value) for key, value in params.items() if value is not None and key != "sign"}
    message = SIGN_PREFIX + "".join(f"{key}{filtered[key]}" for key in sorted(filtered)) + SIGN_PREFIX
    return _sha256_hex(_md5_hex(_md5_hex(_md5_hex(message)))).lower()


def parse_did_mapping(value: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not value:
        return mapping

    for item in value.split(","):
        if not item or "-" not in item:
            continue
        did, payload = item.split("-", 1)
        if did:
            mapping[did] = payload
    return mapping


def did_order(value: str | None) -> list[str]:
    return list(parse_did_mapping(value).keys())


def split_dids(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(",")) if item]


def photo_wall_filename(value: str) -> str:
    return value.rsplit("/", 1)[-1].strip()


def extract_device_meta(payload: dict[str, Any]) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key in DEVICE_META_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            meta[key] = value

    rows = payload.get("data")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in DEVICE_META_KEYS:
                if key in meta:
                    continue
                value = row.get(key)
                if isinstance(value, str) and value:
                    meta[key] = value
            break

    return meta


def build_watch_index(payload: dict[str, Any], user_id: int | None = None) -> dict[str, YQTWatch]:
    meta = extract_device_meta(payload)
    did_names = parse_did_mapping(meta.get("didstr"))
    did_roles = parse_did_mapping(meta.get("didrole"))
    did_types = parse_did_mapping(meta.get("didtype"))
    did_esim = parse_did_mapping(meta.get("isEsim"))
    did_ids = parse_did_mapping(meta.get("total_did_id"))
    did_models = parse_did_mapping(meta.get("total_did_model"))
    did_configs = parse_did_mapping(meta.get("total_did_config"))

    watches: dict[str, YQTWatch] = {}
    for did in did_order(meta.get("didstr")) or did_order(meta.get("total_did_id")):
        watches[did] = YQTWatch(
            did=did,
            did_id=did_ids.get(did, ""),
            model=did_models.get(did, ""),
            nickname=did_names.get(did, ""),
            rolename=did_roles.get(did, ""),
            user_id=user_id,
            config=did_configs.get(did, ""),
            is_esim=did_esim.get(did, ""),
            watch_type=did_types.get(did, ""),
        )
    return watches


def watches_to_rows(watches: dict[str, YQTWatch]) -> list[dict[str, Any]]:
    return [
        {
            "did": watch.did,
            "did_id": watch.did_id,
            "nickname": watch.nickname,
            "rolename": watch.rolename,
            "model": watch.model,
            "config": watch.config,
            "is_esim": watch.is_esim,
            "type": watch.watch_type,
            "user_id": watch.user_id,
        }
        for watch in watches.values()
    ]


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def coerce_accuracy(value: Any) -> int | None:
    parsed = coerce_float(value)
    if parsed is None or parsed <= 0:
        return None
    return round(parsed)


def parse_position_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def extract_address(row: dict[str, Any]) -> str | None:
    for key in ("address", "replacePosition"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_login_timeout_response(payload: dict[str, Any]) -> bool:
    status = coerce_int(payload.get("status"))
    if status == 607:
        return True

    message = str(payload.get("message", "")).lower()
    return "login timeout" in message


def build_watch_state(
    watch: YQTWatch,
    response: dict[str, Any],
    previous: YQTWatchState | None = None,
) -> YQTWatchState:
    status = coerce_int(response.get("status"))
    message = str(response.get("message", ""))
    rows = response.get("data")
    first_row = next((row for row in rows if isinstance(row, dict)), None) if isinstance(rows, list) else None

    if first_row is None:
        if previous is not None:
            return replace(
                previous,
                watch=watch,
                raw_response=response,
                last_poll_status=status,
                last_poll_message=message,
            )

        return YQTWatchState(
            watch=watch,
            raw_response=response,
            last_poll_status=status,
            last_poll_message=message,
        )

    battery = coerce_int(first_row.get("battery"))
    if battery is None:
        battery = coerce_int(response.get("battery"))

    return YQTWatchState(
        watch=watch,
        latitude=coerce_float(first_row.get("lat")),
        longitude=coerce_float(first_row.get("lng")),
        battery=battery,
        last_fix=parse_position_datetime(first_row.get("positiondate")),
        address=extract_address(first_row),
        speed=coerce_float(first_row.get("speed")),
        direction=coerce_float(first_row.get("direction")),
        accuracy=coerce_accuracy(first_row.get("gpsrang")),
        raw_position=first_row,
        raw_response=response,
        last_poll_status=status,
        last_poll_message=message,
    )
