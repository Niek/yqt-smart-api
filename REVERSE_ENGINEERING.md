# YQT SMART Reverse Engineering Notes

Static analysis source:

- `decoded/base/smali_classes3/c7/a.smali` (`SecurityGuardAPI.java`) for Retrofit paths and parameter names.
- `decoded/base/smali_classes3/j7/c.smali` for wrapper methods, base URLs, defaults, and session handling.
- `decoded/base/smali_classes3/d7/b.smali` (`SignUtils.java`) for password hashing and request signing.
- `decoded/base/smali_classes3/f7/b.smali` (`SignInterceptor.java`) for the final signed-wire format.
- `decoded/base/smali_classes3/d7/a.smali` for region backends.

Live validation:

- On 2026-04-15 I sent one fake login request to `https://europe.myaqsh.com:8093/app/public/S10APP/v2_new_userLogin2`.
- The server returned HTTP 200 with:
  `{"status":2,"message":"Either account is not registered, Area selected below is incorrect or your entry may contain spaces."}`
- That confirms the static analysis is good enough to start a Python client.
- On 2026-04-15 I also spot-checked a real Europe account:
  - `v2_sendOrder` with the fresh-location command returned a `code=200` acknowledgement.
  - `v2_findPictrueDoorInfo` returned real photo-wall rows with `path` and `createtime`.
  - `findTalkNewInfo` returned real chat records, including AMR voice-message attachments.

White-label note:

- The APK is branded `YQT SMART`, but the assets and code also reference `KiDSnav` and `MonitorGPS`.
- Your note about `SeTracker`, `SeTracker 2`, and `CarePro+` using the same backend is consistent with what the APK suggests.
- Treat this backend as an OEM/shared platform rather than a YQT-only API.

## Important findings

### 1. Base endpoints by region

The app keeps four server values per region:

- `BASE_URL`: primary API host
- `BASE_COLLECTION_URL`: secondary collection host
- `BIND_URL`: push/bind host
- `MQTT_SERVER`: MQTT broker

Examples:

- `europe`
  - `BASE_URL`: `https://europe.myaqsh.com:8093`
  - `BASE_COLLECTION_URL`: `https://europe.myaqsh.com:8082`
  - `BIND_URL`: `https://europe.myaqsh.com:8084`
  - `MQTT_SERVER`: `tcp://52.28.132.157:1883`
- `asia`
  - `BASE_URL`: `https://asia.myaqsh.com:8093`
  - `BASE_COLLECTION_URL`: `https://asia.myaqsh.com:8082`
  - `BIND_URL`: `https://asia.myaqsh.com:8084`
  - `MQTT_SERVER`: `tcp://54.169.10.136:1883`
- `northam`
  - `BASE_URL`: `https://northam.myaqsh.com:8093`
  - `MQTT_SERVER`: `tcp://54.153.6.9:1883`
- `southam`
  - `BASE_URL`: `https://southam.myaqsh.com:8093`
  - `MQTT_SERVER`: `tcp://54.207.93.14:1883`
- `hk`
  - `BASE_URL`: `https://hk.myaqsh.com:8093`
  - `MQTT_SERVER`: `tcp://47.91.138.192:1883`
- `vie`
  - `BASE_URL`: `https://vie.myaqsh.com:8093`
  - `MQTT_SERVER`: `tcp://103.7.40.198:1883`
- `russ`
  - `BASE_URL`: `https://russ.myaqsh.com:8093`
  - `MQTT_SERVER`: `tcp://156.229.16.166:1883`

There is also a Shenzhen default set used for upload and fallback values:

- `https://sz.myaqsh.com:8093`
- `https://sz.myaqsh.com:8098`
- `https://sz.myaqsh.com:8087`
- upload default `https://sz.myaqsh.com:10000`
- MQTT fallback `tcp://sz.myaqsh.com:1883`

### 2. Session handling

- After login, the app stores `UserLoginResponse.sid` as `session_id`.
- Many device APIs use `/app/{sid}/...`, so `sid` is required after login.
- The app also persists cookies from `Set-Cookie`, but the basic login probe worked without pre-existing cookies.
- On the live account, `v2_findLastPosition`, `v2_findDeviceSwitch`, and `v2_findAlarmInfo` all rejected requests with `status=-2` and `message="params error"` unless `did_id` was sent alongside `did`.

### 3. Password hashing

The Android app does not send the raw password.

It transforms it as:

1. `md5(password)`
2. `sha256(result_of_step_1)`

So:

```text
password_wire = sha256(md5(password))
```

### 4. Request signing

Requests marked with `KEY_NEW_SIGN` are rewritten by the OkHttp interceptor before going on the wire.

The final signed request looks like this:

- `sign_flag=KHDIW`
- `sign=<computed_signature>`
- no `KEY_NEW_SIGN` query parameter

Signature algorithm:

1. Collect all request parameters except `sign` and the `KEY_NEW_SIGN...` marker params.
2. Sort parameter names lexicographically.
3. Build:

```text
SECRPRO + key1 + value1 + key2 + value2 + ... + SECRPRO
```

4. Compute:

```text
sign = sha256(md5(md5(md5(built_string)))).lower()
```

### 5. Login defaults used by the app

The Android login flow hardcodes:

- `appid=aaagg11145`
- `flag=394`
- `version=1.0.1`
- `isIPHONE=1`
- `language=enUS` by default for English
- `sign_flag=KHDIW`

The `isIPHONE` name is misleading; the Android app still sends `1`.

## Useful endpoints

### Login

- `POST /app/public/S10APP/v2_new_userLogin2`
- Fields:
  - `language`
  - `appid`
  - `password`
  - `loginname`
  - `flag`
  - `version`
  - `isIPHONE`
  - `timestamppp`
  - `sign_flag`
  - `sign`

Response model:

- `status`
- `message`
- `sid`
- `data` (list of users)
- `total_did_id`
- `total_did_config`
- `total_did_model`

### Find user devices

- `GET /app/public/S10APP/v2_new_findUserDeviceInfo`
- Query:
  - `language`
  - `timestamppp`
  - `user_id`
  - `loginname`
  - `type`
  - `sign_flag`
  - `sign`

Response data is a list of `UserDeviceInfo`.

### Find device list metadata

- `GET /app/public/S10APP/v2_findDeviceListByUserId`
- Query:
  - `language`
  - `timestamppp`
  - `user_id`
  - `loginname`
  - `sign_flag`
  - `sign`

Response includes:

- `didstr`
- `didrole`
- `total_did_id`
- `total_did_config`
- `total_did_model`

This may be useful when the plain device list does not expose enough `did_id` context.

### Last position

- `GET /app/{sid}/S10APP/v2_findLastPosition`
- Query:
  - `language`
  - `did_id`
  - `did`
  - `timestamppp`
  - `sign_flag`
  - `sign`
  - optional `id`

Response fields include:

- `battery`
- `data` list with `lat`, `lng`, `speed`, `direction`, `positiondate`, `address`, `tmp_wifi`, and related fields.

### Multiple-device last position

- `GET /app/{sid}/S10APP/v2_findLastPositionByMore`
- Query:
  - `language`
  - `loginname`
  - `dids`
  - `did`
  - `timestamppp`
  - `sign_flag`
  - `sign`
  - optional `id`

### Alarm history

- `GET /app/{sid}/S10APP/v2_findAlarmInfo`
- Query:
  - `language`
  - `did`
  - `did_id`
  - `flag`
  - `count`
  - `createtime`
  - `timestamppp`
  - `sign_flag`
  - `sign`

### Device switches

- `GET /app/{sid}/S10APP/v2_findDeviceSwitch`
- Query:
  - `did_id`
  - `did`
  - `language`
  - `timestamppp`
  - `sign_flag`
  - `sign`

## Feature-specific commands

Two separate command families show up in this APK:

- `POST /app/{sid}/S10APP/v2_sendOrder` for most watch commands
- `POST /S10APP/retrieveDeviceInfo` for some lost-device helpers such as ringing the watch and fetching nearby photos

The `sendOrder` payload shape is:

- `sid`
- `language`
- `sendurl`
- `timestamppp`
- `sign_flag`
- `sign`

One important quirk: `v2_sendOrder` replies with `code=200` style command acknowledgements, not the usual `status=1` / `message=...` envelope.

### Get fresh position

The app does not call a separate "refresh now" location endpoint. It sends an async command, then polls normal position data.

- Client status:
  - implemented in `yqt_client.py` as `fresh-position`
  - follow-up polling implemented as `last-position` / `last-positions`
- Trigger:
  - `POST /app/{sid}/S10APP/v2_sendOrder`
  - `sendurl=test?dev_id=<did>&com=D3&dev_model=<model>`
- Follow-up read:
  - `GET /app/{sid}/S10APP/v2_findLastPosition`
- Live confirmation:
  - the backend acknowledged the command with a payload shaped like:
    `{"dev_id":"...","com":"D3","code":200,"current_utc_time":"..."}`
- UI string `location_success` matches this behavior:
  - "The positioning command was sent successfully, please wait for refresh!"

### Message read/send

Read chat history:

- Client status:
  - read implemented as `chat-read`
  - text send implemented as `chat-send`
  - attachment download still pending
- `POST /app/{sid}/S10APP/findTalkNewInfo`
- Fields:
  - `language`
  - `user_id`
  - `did_id`
  - `did`
  - `create_time`
  - `timestamppp`
  - `sign_flag`
  - `sign`
- Live confirmation:
  - this returned real rows with fields such as `id`, `device_info_id`, `file_type`, `path`, and `create_time`
  - on the tested account the returned rows were voice messages with `.amr` paths
  - after clearing Android app storage and logging in again, the app showed the same 3 rows, so this does not appear to have a historical paging mode
  - a fresh app-to-watch text sent via `addTalkNewInfo` did not show up via a follow-up `chat-read`, so this endpoint appears to behave like "new inbound messages from watch" rather than a full bidirectional thread export

Send text or generic chat/file messages:

- `POST /app/{sid}/S10APP/addTalkNewInfo`
- Multipart body
- Wrapper `j7/c.i(...)` builds:
  - `language`
  - `timestamppp`
  - `did_id`
  - `did`
  - `user_id`
  - `loginname`
  - `file_type`
  - `flag`
  - `app_flag=394`
  - `sign_flag`
  - optional `message`
  - optional multipart `data` file part
  - `sign`
- Live confirmation:
  - plain text works with:
    - `file_type=3`
    - `flag=1`
    - `message=<text>`
  - the server returned:
    - `{"status":1,"message":"OK ","current_utc_time":"..."}`
- This looks like the main generic send-text / send-file entrypoint for one-to-one watch chat.

Send voice/audio:

- `POST /app/{sid}/S10APP/v2_post_audiorecord`
- Multipart body
- Wrapper `j7/c.n3(user_id, did_id, did, imei, file)`

Send photo:

- `POST /app/{sid}/S10APP/v2_post_photoInfo`
- Multipart body
- Wrapper `j7/c.o3(user_id, did_id, did, imei, file)`

Download attachments:

- `GET /app/{sid}/S10APP/v2_get_file`
- Query:
  - `language`
  - `timestamppp`
  - `did_id`
  - `did`
  - `dev_id`
  - `filename`
  - `type`
  - `sign_flag`
  - `sign`
- The app also builds direct signed download URLs against:
  - `GET /app/{sid}/S10APP/v2_file_download`
  - using stored `path` values from the chat/photo records

### Play sounds on device

This feature is implemented as a lost-device helper, not a normal `sendOrder` command.

- Client status:
  - pending
- Endpoint:
  - `POST /S10APP/retrieveDeviceInfo`
- Fields:
  - `a=playvoice`
  - `play_status=1` to start
  - `play_status=0` to stop
  - `did`
  - `did_id`
  - `language`
  - `timestamppp`
  - `sign_flag`
  - `sign`
- UI behavior from `RetrieveDeviceSoundActivity`:
  - the main button sends `play_status=1`
  - the dialog stop button sends `play_status=0`
  - the dialog also auto-sends `play_status=0` after 60 seconds
- Live note:
  - on my probe, both start and stop calls timed out instead of returning a clean JSON ack
  - that suggests the server may wait on a device-side flow here, so client code should treat this endpoint carefully

### Remote camera

There are two camera-related features in this APK: still-photo capture and live video monitoring.

- Client status:
  - pending
  - can be approximated manually today via raw `send-order`
Still-photo remote capture:

- Trigger:
  - `POST /app/{sid}/S10APP/v2_sendOrder`
- Known `sendurl` variants:
  - default camera: `test?dev_id=<did>&com=D75`
  - front camera on supported devices: `test?dev_id=<did>&com=D134`
- The Photo Wall presenter uses these commands, then refreshes the gallery.

Live video monitoring ("Video Guardianship"):

- The app sends a `v2_sendOrder` command to start the video-monitoring flow.
- Known builders:
  - `test?dev_id=<did>&com=D196&param1=<loginname>&param2=<...>&param3=<...>`
  - some variants append `&param4=2`
- While a live session is active, switching the watch camera uses:
  - `test?dev_id=<did>&com=D197`
- The actual media/session transport is handled elsewhere in the app, not by a simple REST polling endpoint.

### Gallery

Photo Wall gallery:

- Client status:
  - list implemented as `photowall-list`
  - direct image download implemented as `photowall-download`
  - local cache mirroring intentionally not implemented
- List:
  - `GET /app/{sid}/S10APP/v2_findPictrueDoorInfo`
- Query:
  - `language`
  - `timestamppp`
  - `did`
  - `max_id`
  - `sign_flag`
  - `sign`
- Download image:
  - `GET /app/{sid}/S10APP/v2_downloadPictrueDoor`
- Query:
  - `timestamppp`
  - `did`
  - `filename`
  - `sign_flag`
  - `sign`
- Live confirmation:
  - the tested account returned real gallery rows with fields like `id`, `type`, `path`, and `createtime`
  - `photowall-download` works when `filename` is the basename only, for example `2026-04-14-16-49-33.jpg`
  - sending the full stored path to `v2_downloadPictrueDoor` returned HTTP 404 `read: error`
  - the final wire format uses normal `sign`, not a literal `KEY_NEW_SIGN` query parameter

Lost-device "nearby photos":

- Client status:
  - pending
- Endpoint:
  - `POST /S10APP/retrieveDeviceInfo`
- Fields:
  - `a=photo`
  - `did`
  - `did_id`
  - `language`
  - `timestamppp`
  - `sign_flag`
  - `sign`
- This is the "Nearby photos" view under the retrieve-device flow.
- Live note:
  - the tested account returned `{"status":3,"message":"empty"}` when no lost-device photos were available

### Remote restart

Remote restart is a normal `sendOrder` command:

- Client status:
  - pending as a dedicated helper
  - already possible via raw `send-order`
- `POST /app/{sid}/S10APP/v2_sendOrder`
- `sendurl=test?dev_id=<did>&com=D2&dev_model=<model>`

Related commands in the same action family:

- factory reset:
  - `test?dev_id=<did>&com=D160`
- remote shutdown:
  - `test?dev_id=<did>&com=D17&dev_model=<model>`

Do not confuse restart with `D197`; `D197` is the live-video camera-switch command.

### Time sync

In this APK, time sync is implemented as a full `sendOrder` command carrying both timezone and current time.

- Client status:
  - pending as a dedicated helper
  - already possible via raw `send-order` once the timezone payload builder is reproduced
- Trigger:
  - `POST /app/{sid}/S10APP/v2_sendOrder`
  - `sendurl=test?dev_id=<did>&com=D280&param1=<tz_value>&param2=<urlencoded_yyyy-MM-dd_HH:mm:ss>`
- `param1` is not the raw IANA timezone id.
  - The app computes a timezone offset-like value via `p4/a.a()`, taking DST into account.
- The activity string matches the implementation:
  - "Synchronize the phone's time and time zone to the watch"

There is also an older/simple `CMDUtils.s(did, int)` builder for `D57`, but `TimeSynActivity` in this APK uses `D280`, not `D57`.

### Practical quirks from live testing

- `v2_findAlarmInfo` may return `{"status":2,"message":"No new data"}` for a valid empty result set.
- `v2_findLastPositionByMore` is not a true bulk endpoint in the obvious sense:
  - sending `dids` without a non-empty `did` returned `status=-2` / `params error`
  - sending both `dids` and one selected `did` returned a valid payload for that selected device
- For Home Assistant, polling `v2_findLastPosition` per device is more reliable than relying on `v2_findLastPositionByMore`.

## Python prototype

The companion file [`yqt_client.py`](/Users/niek/Documents/Code/YQT/yqt_client.py) implements:

- the password hash
- the request sign algorithm
- region presets
- cookie/session handling
- a growing set of high-value endpoints
- a small CLI for manual probing

Implemented CLI commands:

- `login`
- `devices`
- `device-list-meta`
- `send-order`
- `fresh-position`
- `last-position`
- `last-positions`
- `alarms`
- `switches`
- `photowall-list`
- `photowall-download`
- `chat-read`
- `chat-send`

Still pending as dedicated helpers:

- chat send:
  - `v2_post_audiorecord`
  - `v2_post_photoInfo`
- chat attachment download:
  - `v2_get_file`
  - `v2_file_download`
- lost-device sound playback:
  - `retrieveDeviceInfo a=playvoice`
- remote camera helpers:
  - `D75`
  - `D134`
  - `D196`
  - `D197`
- remote restart helper:
  - `D2`
- time sync helper:
  - `D280`
- lost-device nearby photos:
  - `retrieveDeviceInfo a=photo`

## Home Assistant direction

The cleanest first HA integration is probably polling, not MQTT:

1. config flow: username, password, region
2. login once, store `sid` and cookies in `ConfigEntry.runtime_data`
3. coordinator:
   - `find_user_device_info`
   - `find_last_position` for each device
   - optionally `find_alarm_info`
4. entities:
   - `device_tracker`
   - battery sensor
   - last-seen sensor
   - maybe alarm/event sensor later

MQTT is promising for push updates, but I have not extracted the topic layout yet.
