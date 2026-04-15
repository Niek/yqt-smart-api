from __future__ import annotations

from datetime import timedelta

from .core.protocol import DEFAULT_REGION

DOMAIN = "yqt"
TITLE = "YQT Smart"
MANUFACTURER = "YQT Smart"

CONF_LOGINNAME = "loginname"
CONF_PASSWORD = "password"
CONF_REGION = "region"

POLL_INTERVAL = timedelta(minutes=5)
LOCATION_STALE_AFTER = timedelta(minutes=30)
REQUEST_LOCATION_REFRESH_DELAY = 20
