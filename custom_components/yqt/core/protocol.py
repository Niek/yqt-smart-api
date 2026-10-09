from __future__ import annotations

import hashlib
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
UP_NEW_DND_SET_INFO_PATH = "/S10APP/upNewDndSetInfo"
FIND_SET_INFO_PATH_SUFFIX = "/S10APP/v2_findSetInfo"
MAX_DND_PERIODS = 4
DND_OPEN_FLAG_ENABLED = "2"
DND_OPEN_FLAG_DISABLED = "1"
DISABLED_DND_PERIOD = "00:00-00:00-0000000"
DND_CLI_WEEKDAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


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
    """One scheduled Do Not Disturb window for current-generation (DC == 2) watches.

    `weekdays` holds integers 0 (Sunday) through 6 (Saturday), matching
    the bit order of the `new_dndN` period string the APK sends, e.g. Monday
    through Friday is encoded as the bitmap "0111110".

    Times use the watch's local clock. Like the APK, only same-day windows
    are accepted. Enabled means scheduled, not necessarily active right now.
    """

    start: str
    end: str
    weekdays: frozenset[int] = field(default_factory=frozenset)
    enabled: bool = True

    def __post_init__(self) -> None:
        _validate_time_of_day(self.start)
        _validate_time_of_day(self.end)
        invalid_days = {day for day in self.weekdays if day not in range(7)}
        if invalid_days:
            raise ValueError(f"weekdays must be 0 (Sunday) through 6 (Saturday), got {sorted(invalid_days)}")
        if not self.enabled and self.start == self.end == "00:00" and not self.weekdays:
            return
        if self.start >= self.end:
            raise ValueError("DND start must be before end; overnight periods are not supported")
        if not self.weekdays:
            raise ValueError("a DND period needs at least one weekday")

    @classmethod
    def disabled(cls) -> DndPeriod:
        """An explicitly empty, disabled period -- used to clear/pad a schedule slot."""
        return cls(start="00:00", end="00:00", weekdays=frozenset(), enabled=False)

    @property
    def open_flag(self) -> str:
        return DND_OPEN_FLAG_ENABLED if self.enabled else DND_OPEN_FLAG_DISABLED

    def to_period_string(self) -> str:
        bitmap = "".join("1" if day in self.weekdays else "0" for day in range(7))
        return f"{self.start}-{self.end}-{bitmap}"

    @classmethod
    def from_period_string(cls, period: str, open_flag: str) -> DndPeriod:
        """Parse one `new_dndN` period string plus its `new_dndN_open` flag.

        Preserve the configured times and weekdays even when disabled.
        Malformed periods and unknown flags raise ValueError.
        """
        if open_flag not in (DND_OPEN_FLAG_ENABLED, DND_OPEN_FLAG_DISABLED):
            raise ValueError(f"invalid DND open flag: {open_flag!r}")

        parts = period.split("-")
        if len(parts) != 3:
            raise ValueError(f"invalid DND period string: {period!r}")
        start, end, bitmap = parts
        if len(bitmap) != 7 or any(char not in "01" for char in bitmap):
            raise ValueError(f"invalid DND weekday bitmap: {bitmap!r}")
        weekdays = frozenset(day for day, flag in enumerate(bitmap) if flag == "1")
        return cls(start=start, end=end, weekdays=weekdays, enabled=open_flag == DND_OPEN_FLAG_ENABLED)

    @classmethod
    def from_cli_string(cls, value: str) -> DndPeriod:
        """Parse "START-END:DAYS", e.g. "08:00-15:00:mon,tue,wed,thu,fri".

        Shared by the CLI's `--period` flag (yqt_client.py) and the
        `set_dnd_schedule` Home Assistant service. Raises ValueError with a
        human-readable message on anything malformed.
        """
        try:
            time_part, days_part = value.rsplit(":", 1)
            start, end = time_part.split("-")
        except ValueError as exc:
            raise ValueError(
                f"invalid period {value!r}; expected START-END:DAYS, "
                "e.g. 08:00-15:00:mon,tue,wed,thu,fri"
            ) from exc

        weekdays: set[int] = set()
        for token in days_part.split(","):
            name = token.strip().lower()
            if name not in DND_CLI_WEEKDAY_NAMES:
                raise ValueError(
                    f"invalid weekday {token!r} in period {value!r}; use sun,mon,tue,wed,thu,fri,sat"
                )
            weekdays.add(DND_CLI_WEEKDAY_NAMES.index(name))

        return cls(start=start, end=end, weekdays=frozenset(weekdays))


def extract_dnd_periods(payload: dict[str, Any]) -> list[DndPeriod] | None:
    """Read four slots, tolerating empty disabled defaults but not corrupt enabled slots."""
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
        # APK DndActivity1.F8: only 2 is enabled; other flags are disabled.
        enabled = str(source.get(f"new_dnd{index}_open")) == DND_OPEN_FLAG_ENABLED
        open_flag = DND_OPEN_FLAG_ENABLED if enabled else DND_OPEN_FLAG_DISABLED
        try:
            periods.append(DndPeriod.from_period_string(str(period_str), open_flag))
        except ValueError:
            if enabled:
                return None
            periods.append(DndPeriod.disabled())
    return periods


def _validate_time_of_day(value: str) -> None:
    parts = value.split(":")
    if len(parts) != 2 or len(value) != 5 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError(f"invalid HH:mm time: {value!r}")
    hours, minutes = parts
    if not (value.isascii() and hours.isdigit() and minutes.isdigit() and 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        raise ValueError(f"invalid HH:mm time: {value!r}")


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
