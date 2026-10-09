from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any


DEFAULT_REGION = "europe"
DEFAULT_LANGUAGE = "enUS"
DEFAULT_APP_ID = "aaagg11145"
DEFAULT_CLIENT_FLAG = 394
DEFAULT_CLIENT_VERSION = "1.0.2"
DEFAULT_IS_IPHONE = 1
DEFAULT_SIGN_FLAG = "KHDIW"
SIGN_PREFIX = "SECRPRO"
SUCCESS_STATUSES = {1, 4}
DEVICE_OFFLINE_STATUS = 601
DEVICE_OFFLINE_MESSAGE = "Device is offline. Check coverage or settings."
DEVICE_META_KEYS = (
    "didstr",
    "didrole",
    "didtype",
    "isEsim",
    "total_did_id",
    "total_did_model",
    "total_did_config",
)

# APK 1.1.5 DC == 2 schedule protocol; contributor-reported read/write validation:
# https://github.com/Niek/yqt-smart-api/issues/13#issuecomment-6066936144
MAX_DND_PERIODS = 4
DND_OPEN_FLAG_ENABLED = "2"
DND_OPEN_FLAG_DISABLED = "1"
DISABLED_DND_PERIOD = "00:00-00:00-0000000"
DND_WEEKDAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_DND_TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
_DND_WIRE = re.compile(rf"({_DND_TIME})-({_DND_TIME})-([01]{{7}})")
_DND_INPUT = re.compile(rf"({_DND_TIME})-({_DND_TIME}):([a-z, ]+)", re.IGNORECASE | re.ASCII)


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
        base_url="https://europe.myaqsh.com:11001",
        collection_url="https://europe.myaqsh.com:11002",
        bind_url="https://europe.myaqsh.com:11003",
        mqtt_url="mqtts://europe.myaqsh.com:8883",
    ),
    "asia": RegionConfig(
        name="asia",
        base_url="https://asia.myaqsh.com:11001",
        collection_url="https://asia.myaqsh.com:11002",
        bind_url="https://asia.myaqsh.com:11003",
        mqtt_url="mqtts://asia.myaqsh.com:8883",
    ),
    "northam": RegionConfig(
        name="northam",
        base_url="https://northam.myaqsh.com:11001",
        collection_url="https://northam.myaqsh.com:11002",
        bind_url="https://northam.myaqsh.com:11003",
        mqtt_url="mqtts://northam.myaqsh.com:8883",
    ),
    "southam": RegionConfig(
        name="southam",
        base_url="https://southam.myaqsh.com:11001",
        collection_url="https://southam.myaqsh.com:11002",
        bind_url="https://southam.myaqsh.com:11003",
        mqtt_url="mqtts://southam.myaqsh.com:8883",
    ),
    "hk": RegionConfig(
        name="hk",
        base_url="https://hk.myaqsh.com:11001",
        collection_url="https://hk.myaqsh.com:11002",
        bind_url="https://hk.myaqsh.com:11003",
        mqtt_url="mqtts://hk.myaqsh.com:8883",
    ),
    "vie": RegionConfig(
        name="vie",
        base_url="https://vie.myaqsh.com:11001",
        collection_url="https://vie.myaqsh.com:11002",
        bind_url="https://vie.myaqsh.com:11003",
        mqtt_url="mqtts://vie.myaqsh.com:8883",
    ),
    "russ": RegionConfig(
        name="russ",
        base_url="https://russ.myaqsh.com:11001",
        collection_url="https://russ.myaqsh.com:11002",
        bind_url="https://russ.myaqsh.com:11003",
        mqtt_url="mqtts://russ.myaqsh.com:8883",
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
    wifi_access_points: list[dict[str, object]] = field(default_factory=list)
    cell_towers: list[dict[str, object]] = field(default_factory=list)
    raw_position: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)
    last_poll_status: int | None = None
    last_poll_message: str = ""


@dataclass(frozen=True, slots=True)
class DndPeriod:
    """Enabled window in watch-local time; weekday bits run Sunday (0) to Saturday (6)."""

    start: str
    end: str
    weekdays: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        # Validate direct construction as well as parsed CLI and wire inputs.
        if not re.fullmatch(rf"{_DND_TIME}-{_DND_TIME}", f"{self.start}-{self.end}"):
            raise ValueError("DND times must use HH:mm (00:00 through 23:59)")
        if not self.weekdays <= frozenset(range(7)):
            raise ValueError("weekdays must be 0 (Sunday) through 6 (Saturday)")
        if self.start >= self.end:
            raise ValueError("DND start must be before end; overnight periods are not supported")
        if not self.weekdays:
            raise ValueError("a DND period needs at least one weekday")

    @property
    def weekday_names(self) -> list[str]:
        return [DND_WEEKDAY_NAMES[day] for day in sorted(self.weekdays)]

    def __str__(self) -> str:
        return f"{self.start}-{self.end}:{','.join(self.weekday_names)}"

    def to_period_string(self) -> str:
        bitmap = "".join("1" if day in self.weekdays else "0" for day in range(7))
        return f"{self.start}-{self.end}-{bitmap}"

    @classmethod
    def from_period_string(cls, period: str) -> DndPeriod:
        if not (match := _DND_WIRE.fullmatch(period)):
            raise ValueError(f"invalid DND period string: {period!r}")
        start, end, bitmap = match.groups()
        return cls(start, end, frozenset(day for day, flag in enumerate(bitmap) if flag == "1"))

    @classmethod
    def parse(cls, value: str) -> DndPeriod:
        """Parse START-END:DAYS for the CLI and HA action."""
        if not (match := _DND_INPUT.fullmatch(value)):
            raise ValueError(f"invalid period {value!r}; expected HH:mm-HH:mm:mon,tue,...")
        start, end, days = match.groups()
        names = {token.strip().lower() for token in days.split(",")}
        if not names <= set(DND_WEEKDAY_NAMES):
            raise ValueError(f"invalid weekdays {days!r}; use sun,mon,tue,wed,thu,fri,sat")
        return cls(start, end, frozenset(DND_WEEKDAY_NAMES.index(name) for name in names))


def extract_dnd_periods(payload: dict[str, Any]) -> list[DndPeriod] | None:
    """Read enabled, non-empty slots; incomplete or corrupt enabled schedules are unknown."""
    if not isinstance(payload, dict):
        return None
    source: dict[str, Any] = payload
    data = payload.get("data")
    if isinstance(data, dict):
        source = data
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        source = data[0]

    periods: list[DndPeriod] = []
    for index in range(1, MAX_DND_PERIODS + 1):
        if f"new_dnd{index}" not in source or f"new_dnd{index}_open" not in source:
            return None
        period_str = source.get(f"new_dnd{index}")
        # APK treats the sentinel as empty and only flag 2 as enabled.
        if period_str == DISABLED_DND_PERIOD or str(source[f"new_dnd{index}_open"]) != DND_OPEN_FLAG_ENABLED:
            continue
        try:
            periods.append(DndPeriod.from_period_string(str(period_str)))
        except ValueError:
            return None
    return periods


def dnd_schedule_fields(periods: Sequence[DndPeriod]) -> dict[str, str]:
    """Encode a complete schedule, clearing unused slots."""
    if len(periods) > MAX_DND_PERIODS:
        raise YQTError(f"DND supports at most {MAX_DND_PERIODS} periods, got {len(periods)}")
    fields = {}
    slots = [*periods, *[None] * (MAX_DND_PERIODS - len(periods))]
    for index, period in enumerate(slots, start=1):
        fields[f"new_dnd{index}"] = period.to_period_string() if period else DISABLED_DND_PERIOD
        fields[f"new_dnd{index}_open"] = DND_OPEN_FLAG_ENABLED if period else DND_OPEN_FLAG_DISABLED
    return fields


def supports_dnd_schedule(config: str) -> bool:
    """APK DeviceParseUtils: underscore-separated KEY:value pairs; DC:2 is new DND."""
    settings = dict(item.split(":", 1) for item in config.split("_") if ":" in item)
    return settings.get("DC") == "2"


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


def clean_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed = str(value).strip()
    return parsed or None


def parse_wifi_access_points(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []

    access_points: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, str):
            continue

        parts = item.split(",", 2)
        if len(parts) < 2:
            continue

        bssid = clean_string(parts[0])
        signal_dbm = coerce_int(parts[1])
        if bssid is None or signal_dbm is None:
            continue

        access_points.append(
            {
                "bssid": bssid,
                "signal_dbm": signal_dbm,
                "ssid": parts[2].strip() if len(parts) > 2 else "",
            }
        )
    return access_points


def parse_cell_towers(row: dict[str, Any]) -> list[dict[str, object]]:
    mcc = clean_string(row.get("mcc"))
    mnc = clean_string(row.get("mnc"))
    cells = row.get("tmp_base")
    if mcc is None or mnc is None or not isinstance(cells, list):
        return []

    towers: list[dict[str, object]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue

        lac = clean_string(cell.get("lac"))
        cid = clean_string(cell.get("cid"))
        if lac is None or cid is None:
            continue

        towers.append(
            {
                "mcc": mcc,
                "mnc": mnc,
                "lac": lac,
                "cid": cid,
                "rxlev": coerce_int(cell.get("rxlev")),
            }
        )
    return towers


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

    latitude = coerce_float(first_row.get("lat"))
    longitude = coerce_float(first_row.get("lng"))

    if abs(coerce_int(first_row.get("datatype")) or 0) == 3:
        corrected_latitude = coerce_float(first_row.get("lat_co"))
        corrected_longitude = coerce_float(first_row.get("lng_co"))
        if (
            corrected_latitude is not None
            and corrected_longitude is not None
            and (corrected_latitude != 0 or corrected_longitude != 0)
        ):
            latitude = corrected_latitude
            longitude = corrected_longitude

    if latitude == 0 and longitude == 0:
        if previous is not None:
            return replace(
                previous,
                watch=watch,
                raw_response=response,
                last_poll_status=status,
                last_poll_message=message,
            )
        first_row = {}
        latitude = longitude = None

    return YQTWatchState(
        watch=watch,
        latitude=latitude,
        longitude=longitude,
        battery=battery,
        last_fix=parse_position_datetime(first_row.get("positiondate")),
        address=extract_address(first_row),
        speed=coerce_float(first_row.get("speed")),
        direction=coerce_float(first_row.get("direction")),
        accuracy=coerce_accuracy(first_row.get("gpsrang")),
        wifi_access_points=parse_wifi_access_points(first_row.get("tmp_wifi")),
        cell_towers=parse_cell_towers(first_row),
        raw_position=first_row,
        raw_response=response,
        last_poll_status=status,
        last_poll_message=message,
    )
