from __future__ import annotations

from datetime import timedelta

from .core.protocol import DEFAULT_REGION

DOMAIN = "yqt"
TITLE = "YQT Smart"
MANUFACTURER = "YQT Smart"

CONF_LOGINNAME = "loginname"
CONF_PASSWORD = "password"
CONF_REGION = "region"

SERVICE_SET_DND_SCHEDULE = "set_dnd_schedule"
ATTR_PERIODS = "periods"

POLL_INTERVAL = timedelta(minutes=5)
LOCATION_STALE_AFTER = timedelta(minutes=30)
REQUEST_LOCATION_REFRESH_DELAY = 20

# Settings change less often than location and are polled independently.
DND_POLL_INTERVAL = timedelta(minutes=30)
