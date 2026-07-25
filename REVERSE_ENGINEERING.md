# YQT SMART Reverse Engineering Notes

This document records protocol behavior observed in the YQT SMART Android app
and through limited live API testing. It distinguishes static APK findings from
live validation because vendor behavior can change without notice.

The backend appears to be a shared OEM platform. The YQT SMART APK also
references `KiDSnav` and `MonitorGPS`, and related apps such as SeTracker,
SeTracker 2, and CarePro+ appear to use the same service.

## Analyzed versions

| APK | Version code | Checked |
| --- | ---: | --- |
| `1.1.1` | 12 | 2026-04-15 |
| `1.1.5` | 16 | 2026-07-25 |

Package name: `com.tgelec.yqtsmart`.

APK `1.1.5` retains the main REST path names from `1.1.1`, but changes the
servers and request transport.

## Current protocol

### Regional servers

APK `1.1.5` uses the same port layout for each configured region:

| Setting | Value |
| --- | --- |
| Primary API | `https://<region>.myaqsh.com:11001` |
| Collection API | `https://<region>.myaqsh.com:11002` |
| Bind service | `https://<region>.myaqsh.com:11003` |
| MQTT | `mqtts://<region>.myaqsh.com:8883` |
| Extra regional endpoint | `https://<region>.myaqsh.com:9500` |

Known region names are `europe`, `asia`, `northam`, `southam`, `hk`, `vie`,
and `russ`.

The APK also contains Shenzhen fallback values:

- `https://sz.myaqsh.com:8093`
- `https://sz.myaqsh.com:8098`
- `https://sz.myaqsh.com:8087`
- `mqtts://sz.myaqsh.com:8883`
- `https://sz.myaqsh.com:18000`

The client currently uses only the primary API. The purpose and transport
requirements of the collection, bind, and extra endpoints have not been
validated.

### TLS client identity

The `:11001`/`:11002`/`:11003` servers require mutual TLS. A plain TLS request
to `:11001` returns HTTP 400:

```text
No required SSL certificate was sent
```

[`custom_components/yqt/core/client.pem`](custom_components/yqt/core/client.pem)
contains the shared client certificate and encrypted private key bundled with
the Android app. It is not a user-specific credential.

- Subject CN: `AQSHAPP-Client-2026-001`
- Valid from: 2026-05-19
- Expires: 2029-05-18

The vendor may replace or revoke this identity before its stated expiry.

### Password hashing

The raw account password is not sent. The app computes:

```text
password_wire = sha256(md5(password))
```

### Inner request and signature

Endpoint parameter lists in this document describe the inner request object,
not the current on-wire query or body.

For a signed request:

1. Add `timestamppp`, normally the current Unix time in milliseconds.
2. Add `sign_flag`; the client currently defaults to `KHDIW`.
3. Add `app_flag=394`.
4. Exclude `sign`, discard null values, and sort parameter names
   lexicographically.
5. Build:

   ```text
   SECRPRO + key1 + value1 + key2 + value2 + ... + SECRPRO
   ```

6. Compute:

   ```text
   sign = sha256(md5(md5(md5(built_string)))).lower()
   ```

7. Add the resulting `sign` to the inner object.

`flag=394`, used by login, and `app_flag=394`, added by the transport, are
separate fields.

APK `1.1.5` can store a server-provided `SignFlag` and pass it into later
requests. Live testing confirmed that the current encrypted login endpoint
still accepts `KHDIW`, so the Python client retains that default.

### Encrypted envelope

Standard API requests use the following transport:

1. Select one of five APK-embedded AES key/IV pairs and its index.
2. For form-style POST operations, percent-encode the inner keys and values.
3. Serialize the signed inner object as compact JSON.
4. Apply PKCS#7 padding and AES-CBC encryption.
5. Hex-encode the ciphertext.
6. Send the outer envelope:

   ```json
   {
     "encryptIndex": 1,
     "encryptData": "<hex ciphertext>"
   }
   ```

For GET requests, the two envelope fields are query parameters. For standard
POST requests, the envelope is a JSON body. Both include:

```text
X-Encrypt-Index: <index>
```

Encrypted API responses use the same envelope and key index. The implementation
lives in
[`custom_components/yqt/core/transport.py`](custom_components/yqt/core/transport.py).

Multipart endpoints are a known exception requiring further validation. The
standalone client's multipart helper still uses the legacy signed multipart
body over mTLS; it has not been confirmed to work after the July 2026 transport
change.

### Login defaults

APK `1.1.5` uses:

- `appid=aaagg11145`
- `flag=394`
- `version=1.0.2`
- `isIPHONE=1`
- `language=enUS` for English
- `sign_flag=KHDIW` initially

`isIPHONE` is sent by the Android app despite its name. The login `version` is a
protocol/client version, not the APK package version.

### Sessions

- Login returns `sid`, which the app stores as `session_id`.
- Most device-specific APIs use `/app/{sid}/...`.
- Public login and device-discovery endpoints use `/app/public/...`.
- The app also persists response cookies.
- `v2_findLastPosition`, `v2_findDeviceSwitch`, and `v2_findAlarmInfo` required
  both `did` and `did_id` during live testing.

## Validation history

| Date | Transport | Result |
| --- | --- | --- |
| 2026-04-15 | Legacy `:8093` | Fake login returned normal status `2`; a real account confirmed fresh-location `sendOrder`, Photo Wall listing, and chat reads. |
| 2026-07-06 | Legacy `:8093` | Login required protocol `version=1.0.2`; `1.0.1` returned an old-version error. Both public and session-bound `v2_new_findUserDeviceByDid` paths returned data. |
| 2026-07-25 | Legacy `:8093` | Login began returning status `3`: “The current app is unavailable. Please upgrade the app.” |
| 2026-07-25 | Current `:11001` | Plain TLS failed for lack of a client certificate. mTLS with the legacy body still returned the forced-upgrade response. mTLS plus the encrypted envelope returned the normal status `2` response for a fake account. |

Feature observations below that are labeled “legacy-live” were not necessarily
retested after the current transport became mandatory.

Evidence labels used below:

- **Current-live:** confirmed against the mTLS and encrypted transport.
- **Legacy-live:** confirmed before the July 2026 transport change.
- **APK:** found through static analysis but not necessarily tested live.
- **Implemented:** present in the Python client but not necessarily revalidated
  live.

## Endpoint reference

Unless an exception is stated, requests are signed and wrapped using the
current transport above. Tables list endpoint-specific inner parameters;
common fields such as `language`, `timestamppp`, `sign_flag`, `app_flag`, and
`sign` are omitted for brevity.

### Account and devices

| Operation | Method and path | Endpoint-specific inner parameters | Evidence |
| --- | --- | --- | --- |
| Login | `POST /app/public/S10APP/v2_new_userLogin2` | `appid`, hashed `password`, `loginname`, `flag`, `version`, `isIPHONE` | Current-live |
| Find user devices | `GET /app/public/S10APP/v2_new_findUserDeviceInfo` | `user_id`, `loginname`, `type` | APK, implemented |
| Device-list metadata | `GET /app/public/S10APP/v2_findDeviceListByUserId` | `user_id`, `loginname` | APK, implemented |
| Find one device | `GET /app/{sid}/S10APP/v2_new_findUserDeviceByDid` | `did`, `did_id` | APK, legacy-live |
| Find one device alias | `GET /app/public/S10APP/v2_new_findUserDeviceByDid` | `did`, `did_id` | Legacy-live, used by the standalone client |

Login responses commonly include:

- `status`
- `message`
- `sid`
- `data`, containing user rows
- `total_did_id`
- `total_did_config`
- `total_did_model`

`v2_findDeviceListByUserId` also returns `didstr` and `didrole`. These values
help map a watch `did` to the `did_id` required by several device APIs.

The APK uses the session-bound `v2_new_findUserDeviceByDid` path. The standalone
client currently uses the public alias because the backend accepted both during
live testing.

### Position, alarms, and switches

| Operation | Method and path | Endpoint-specific inner parameters | Evidence |
| --- | --- | --- | --- |
| Last position | `GET /app/{sid}/S10APP/v2_findLastPosition` | `did`, `did_id`, optional `id` | Legacy-live, implemented |
| Multiple-device position | `GET /app/{sid}/S10APP/v2_findLastPositionByMore` | `loginname`, `dids`, `did`, optional `id` | Legacy-live, implemented |
| Alarm history | `GET /app/{sid}/S10APP/v2_findAlarmInfo` | `did`, `did_id`, `flag`, `count`, `createtime` | Legacy-live, implemented |
| Device switches | `GET /app/{sid}/S10APP/v2_findDeviceSwitch` | `did`, `did_id` | Legacy-live, implemented |

Position responses include `battery` and a `data` list. Position rows can
contain `lat`, `lng`, `speed`, `direction`, `positiondate`, `address`,
`tmp_wifi`, cell-tower data, and related fields.

Observed quirks:

- `v2_findAlarmInfo` can return status `2`, “No new data”, for a valid empty
  result.
- `v2_findLastPositionByMore` rejected `dids` without a non-empty `did`.
- Supplying both `dids` and one selected `did` returned only the selected
  device's useful position data.
- Polling `v2_findLastPosition` per watch is therefore more reliable for Home
  Assistant.

## Commands and feature endpoints

### `v2_sendOrder`

Most watch actions use:

```text
POST /app/{sid}/S10APP/v2_sendOrder
```

The inner payload contains `sid` and `sendurl` in addition to the common signed
fields. Successful command acknowledgements use `code=200`, rather than the
usual `status=1` response shape.

| Action | `sendurl` | Evidence |
| --- | --- | --- |
| Request fresh location | `test?dev_id=<did>&com=D3&dev_model=<model>` | Legacy-live |
| Restart | `test?dev_id=<did>&com=D2&dev_model=<model>` | APK |
| Factory reset | `test?dev_id=<did>&com=D160` | APK |
| Shutdown | `test?dev_id=<did>&com=D17&dev_model=<model>` | APK |
| Default-camera photo | `test?dev_id=<did>&com=D75` | APK |
| Front-camera photo | `test?dev_id=<did>&com=D134` | APK |
| Start video monitoring | `test?dev_id=<did>&com=D196&param1=<loginname>&param2=<...>&param3=<...>` | APK |
| Switch video camera | `test?dev_id=<did>&com=D197` | APK |
| Time sync | `test?dev_id=<did>&com=D280&param1=<tz_value>&param2=<urlencoded time>` | APK |

Fresh location is asynchronous: the app sends `D3`, then polls
`v2_findLastPosition`. A legacy-live acknowledgement looked like:

```json
{"dev_id":"...","com":"D3","code":200,"current_utc_time":"..."}
```

For time sync, `param1` is an app-computed offset-like value that accounts for
DST, not a raw IANA timezone name. `param2` uses `yyyy-MM-dd HH:mm:ss` before
URL encoding. An older `D57` builder also exists, but APK `1.1.5` uses `D280`.

Live video monitoring uses additional media/session handling not covered by
the REST command itself. Some `D196` variants append `param4=2`.

### Chat and attachments

| Operation | Method and path | Endpoint-specific inner parameters | Evidence |
| --- | --- | --- | --- |
| Read new chat rows | `POST /app/{sid}/S10APP/findTalkNewInfo` | `user_id`, `did_id`, `did`, `create_time` | Legacy-live, implemented |
| Send text/file | `POST /app/{sid}/S10APP/addTalkNewInfo` | `did_id`, `did`, `user_id`, `loginname`, `file_type`, `flag`, optional `message`, optional `data` file | Legacy-live; current multipart unverified |
| Upload audio | `POST /app/{sid}/S10APP/v2_post_audiorecord` | `user_id`, `did_id`, `did`, `imei`, file | APK |
| Upload photo | `POST /app/{sid}/S10APP/v2_post_photoInfo` | `user_id`, `did_id`, `did`, `imei`, file | APK |
| Download attachment | `GET /app/{sid}/S10APP/v2_get_file` | `did_id`, `did`, `dev_id`, `filename`, `type` | APK |
| Direct file download | `GET /app/{sid}/S10APP/v2_file_download` | Stored path and signed fields | APK |

Legacy-live chat observations:

- `findTalkNewInfo` returned rows containing fields such as `id`,
  `device_info_id`, `file_type`, `path`, and `create_time`.
- The tested rows were inbound AMR voice messages.
- Clearing app storage and logging in again returned the same three rows, so
  the endpoint did not behave like a complete historical paging API.
- A newly sent app-to-watch text did not appear in a follow-up read, suggesting
  `findTalkNewInfo` is primarily for inbound watch messages.
- Text sending worked with `file_type=3`, `flag=1`, and `message=<text>`.

The current `chat-send` CLI still uses the legacy multipart encoding. Treat it
as unverified until multipart behavior is tested against APK `1.1.5`.

### Photo Wall

| Operation | Method and path | Endpoint-specific inner parameters | Evidence |
| --- | --- | --- | --- |
| List photos | `GET /app/{sid}/S10APP/v2_findPictrueDoorInfo` | `did`, `max_id` | Legacy-live, implemented |
| Download photo | `GET /app/{sid}/S10APP/v2_downloadPictrueDoor` | `did`, `filename` | Legacy-live, implemented |

Legacy-live results contained `id`, `type`, `path`, and `createtime`.
`v2_downloadPictrueDoor` required the basename, such as
`2026-04-14-16-49-33.jpg`; sending the full stored path returned HTTP 404.

Still-photo commands `D75` and `D134` trigger capture. The app then refreshes
the Photo Wall list.

### Lost-device helpers

The APK also uses:

```text
POST /S10APP/retrieveDeviceInfo
```

This path does not follow the normal `/app/{sid}/...` shape. Its current host
selection and encrypted transport behavior have not been revalidated.

| Action | Endpoint-specific fields | Evidence |
| --- | --- | --- |
| Play sound | `a=playvoice`, `play_status=1` or `0`, `did`, `did_id` | APK; legacy calls timed out |
| Nearby photos | `a=photo`, `did`, `did_id` | APK; legacy-live empty response |

The sound dialog sends `play_status=1`, sends `0` when stopped, and
automatically sends `0` after 60 seconds. Both start and stop timed out during
the legacy probe, possibly because the server waits for a device-side flow.

The nearby-photo probe returned status `3`, “empty”, when no photos were
available.

## Implementation status

The shared implementation is under
[`custom_components/yqt/core/`](custom_components/yqt/core/). The executable
CLI is [`yqt_client.py`](yqt_client.py).

| Coverage | Commands/features |
| --- | --- |
| Implemented with the current standard encrypted transport | `login`, `devices`, `device-list-meta`, `send-order`, `fresh-position`, `last-position`, `last-positions`, `alarms`, `switches`, `photowall-list`, `photowall-download`, `chat-read` |
| Implemented through legacy multipart; current behavior unverified | `chat-send` |
| Available through raw `send-order` | Restart and camera/time-sync commands once their parameters are known |
| Not implemented as dedicated helpers | Audio/photo chat upload, attachment download, sound playback, camera/video helpers, restart, time sync, nearby photos |

The Home Assistant integration is already implemented under
[`custom_components/yqt`](custom_components/yqt). It polls device metadata and
last position, and exposes:

- one device per watch
- a last-position `device_tracker`
- battery, last-fix, and speed sensors
- disabled-by-default Wi-Fi and cell-tower diagnostic sensors
- a stale-location binary sensor
- a button that sends `D3` and schedules a later refresh

Installation and user-facing feature documentation belongs in
[`README.md`](README.md), rather than this protocol reference.

## Known gaps and maintenance risks

- Revalidate all legacy-live feature endpoints on the current encrypted
  transport.
- Determine whether multipart operations use a separate encryption rule.
- Extract the MQTT topic and authentication layout before attempting push
  updates.
- Confirm the purpose and security requirements of the collection, bind, and
  extra regional endpoints.
- Track server-provided `SignFlag` behavior if `KHDIW` stops working.
- Replace the bundled client identity if the vendor rotates it or before it
  expires on 2029-05-18.
- Treat endpoint, key, certificate, and APK-version values as vendor-controlled
  implementation details that may change without notice.

## Legacy transport summary

APK `1.1.1` used public REST servers centered on:

- primary API `https://<region>.myaqsh.com:8093`
- collection service `:8082`
- bind service `:8083` or `:8084`
- unencrypted MQTT on port `1883`
- Shenzhen upload fallback on port `10000`

The old primary API accepted directly signed query/form parameters without
mTLS or the encrypted envelope. On 2026-07-25 it began rejecting that client
generation with the forced-upgrade status, so these values are retained only
as historical context.
