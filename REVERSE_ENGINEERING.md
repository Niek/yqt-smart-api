# YQT SMART protocol reference

Based on YQT SMART `1.1.5` (version code 16), package
`com.tgelec.yqtsmart`. The separate [SeTracker2 protocol](SETRACKER2_PROTOCOL.md)
uses different signing and encryption parameters.

## Validation scope

Synthetic login requests verified mTLS, request encryption, and credential-error
response decryption on the primary API. Successful account login and the
feature checks labeled **Legacy-live** used the older HTTPS `:8093` transport,
without the encrypted envelope; those checks do not establish current endpoint
behavior.

Endpoint evidence labels:

- **Current-live:** verified with mTLS and the encrypted envelope; login checks
  used a synthetic account.
- **Legacy-live:** verified on the older transport.
- **APK:** found in the app; not necessarily tested live.
- **Implemented:** available in the Python client; not proof of live behavior.

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

The client currently uses only the primary API. The bind service is used for
[MQTT receiver registration](#mqtt-notifications). The collection and extra
endpoints have not been validated.

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
password_wire = SHA256_hex(MD5_hex(password))
```

Both hashes use lowercase hexadecimal output; the outer hash takes the ASCII
hex digest, not raw MD5 bytes.

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
   sign = SHA256_hex(MD5_hex(MD5_hex(MD5_hex(built_string))))
   ```

7. Add the resulting `sign` to the inner object. Each hash above produces a
   lowercase hexadecimal string for the next hash.

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
body over mTLS; its behavior on the current API is unverified.

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

Login responses include `status`, `message`, `sid`, user rows in `data`,
`total_did_id`, `total_did_config`, and `total_did_model`.

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

### Shared settings and Do Not Disturb

APK `1.1.5` (version code 16) uses these DND endpoints:

| Operation | Method and path | Endpoint-specific inner parameters |
| --- | --- | --- |
| Shared settings read | `GET /app/{sid}/S10APP/v2_findSetInfo` | `did`, `did_id` |
| Four-slot DND write | `POST /S10APP/upNewDndSetInfo` | `sid`, `did`, `did_id`, four `new_dndN` strings and four `new_dndN_open` flags |

The write endpoint has no `/app/{sid}` prefix. Both use the existing signed,
encrypted transport. Settings reads also return phone numbers; HA retains
only parsed DND periods. The CLI exposes the full response for inspection.

The APK selects this four-slot flow for watches with configuration `DC:2`.
Its settings and UI rules are:

- Periods use `HH:mm-HH:mm-xxxxxxx`, with Sunday-first weekday bits
  (`0111110` = Monday–Friday). Start must precede end and at least one day must
  be selected; overnight windows are rejected.
- Flags are `2` for enabled and `1` for disabled. The empty sentinel
  `00:00-00:00-0000000` takes precedence over the flag.
- `data` is a list of settings objects. The write callback accepts `status=1`.

Writes replace all four slots, padding unused slots with the empty sentinel
and flag `1`. An empty list clears the schedule. The client includes `sid` in
the write body, although the APK's declared fields do not require it.

HA omits empty and disabled slots, treats incomplete or malformed enabled
slots as unknown, and refreshes after a successful write. Multi-watch updates
are sequential and may partially succeed. Watch enforcement has not been
independently verified.

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
`v2_findLastPosition`. An acknowledgement does not establish a new location fix.

For time sync, `param1` is an app-computed offset-like value that accounts for
DST, not a raw IANA timezone name. `param2` uses `yyyy-MM-dd HH:mm:ss` before
URL encoding.

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

Chat rows contain `id`, `device_info_id`, `file_type`, `path`, and
`create_time`. Legacy reads returned inbound AMR voice messages; newly sent
app-to-watch text was absent from subsequent reads. Full conversation history
and paging behavior are unverified.

Text sending uses `file_type=3`, `flag=1`, and `message=<text>`. The CLI's
`chat-send` uses legacy multipart encoding, unverified on the current API.

### Photo Wall

| Operation | Method and path | Endpoint-specific inner parameters | Evidence |
| --- | --- | --- | --- |
| List photos | `GET /app/{sid}/S10APP/v2_findPictrueDoorInfo` | `did`, `max_id` | Legacy-live, implemented |
| Download photo | `GET /app/{sid}/S10APP/v2_downloadPictrueDoor` | `did`, `filename` | Legacy-live, implemented |

Legacy-live results contained `id`, `type`, `path`, and `createtime`.
`v2_downloadPictrueDoor` required the basename, such as
`photo.jpg`; sending the full stored path returned HTTP 404.

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
| Play sound | `a=playvoice`, `play_status=1` or `0`, `did`, `did_id` | APK; live operation unverified |
| Nearby photos | `a=photo`, `did`, `did_id` | APK; legacy-live empty response |

The app sends `play_status=1` to start sound and `0` to stop, automatically
stopping after 60 seconds. Nearby-photo requests can return status `3`, “empty”.

## MQTT notifications

YQT SMART `1.1.5` uses `mqtts://<region>.myaqsh.com:8883` for app
notifications. Europe accepts MQTT 3.1.1 over verified TLS without a client
certificate or MQTT username/password. Connection, private-topic subscription
at QoS 0, and push registration have been verified; event delivery and payload
decryption still need a controlled watch-event test.

### Receiver registration

`POST https://<region>.myaqsh.com:11003/push/msg/bindUser` uses mTLS and the
YQT AES envelope. Its inner form values are percent-encoded, with no request
signature. Fields are:

```text
userId=<loginname>, userNick=<loginname>, appId=aaagg11145, pushType=mqtt,
platform=1, softToken=<token>, deviceToken=<token>, imei=<phone identifier>,
push_open=1
```

The private topic is `push/<token>`. The APK derives the token as lowercase
MD5 of the concatenated phone MAC, IMEI (or Android ID), CPU serial, app ID,
and login name. The registration maps this phone-specific token to the account.
`old_imei` is optional and refers to a previous phone identifier; a separate
receiver must not reuse the phone app's identifiers. The endpoint acknowledges
registration and `push_open=0` with `ok`; deletion of a registration is unverified.

The APK uses a clean MQTT session. Its client ID is `394` followed by a
substitution-encoded Android ID, truncated to 22 characters. A standalone
receiver can use a separate random Android ID and subscribe to its private topic.

### Payload and location limits

The APK decodes an optional AES `encryptIndex`/`encryptData` envelope, then
hex-decodes and RC4-decrypts the inner string using the app ID as the key.
The resulting JSON contains `messageList`; each message's `body` is another
JSON string containing an event `type` and usually a `did`.

Static handlers include chat (`2`), administrator requests/approvals (`11`/`12`),
and remote-photo notifications (`36`). The inspected notification model has
no position coordinates, and the map separately calls `v2_findLastPosition`.
No location-update event has been established. MQTT may support event-triggered
refreshes, but it is not yet a verified replacement for position polling.

## Implementation status

The shared implementation is under
[`custom_components/yqt/core/`](custom_components/yqt/core/). The executable
CLI is [`yqt_client.py`](yqt_client.py).

| Coverage | Commands/features |
| --- | --- |
| Implemented with the current standard encrypted transport | `login`, `devices`, `device-list-meta`, `send-order`, `fresh-position`, `last-position`, `last-positions`, `alarms`, `switches`, `find-settings`, `set-dnd`, `photowall-list`, `photowall-download`, `chat-read` |
| Implemented through legacy multipart; current behavior unverified | `chat-send` |
| Available through raw `send-order` | Restart and camera/time-sync commands once their parameters are known |
| Not implemented as dedicated helpers | Audio/photo chat upload, attachment download, sound playback, camera/video helpers, restart, time sync, nearby photos |

See [README.md](README.md) for Home Assistant features and installation.

## Known gaps and maintenance risks

- Revalidate all legacy-live feature endpoints on the current encrypted
  transport.
- Determine whether multipart operations use a separate encryption rule.
- Verify MQTT event delivery, payload decryption, and whether any event signals
  a new position before reducing polling.
- Confirm the collection and extra regional endpoints; the bind endpoint used
  for MQTT registration is described above.
- Track server-provided `SignFlag` behavior if `KHDIW` stops working.
- Replace the bundled client identity if the vendor rotates it or before it
  expires on 2029-05-18.
- Treat endpoint, key, certificate, and APK-version values as vendor-controlled
  implementation details that may change without notice.
