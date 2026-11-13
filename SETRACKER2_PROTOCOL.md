# SeTracker2 protocol

This reference covers the HMAC authentication and index-22 encryption variant
of SeTracker2, implemented in [`yqt_client.py`](yqt_client.py) through
`--protocol setracker2`. Account login, session reuse, device metadata/listing,
and last-position reads have been verified on Europe `:9401`. Home Assistant
continues to use the YQT protocol.

## App and transport

Cryptographic primitives were checked against SeTracker2 `3.4.7` (version code
127), package `com.tgelec.setracker`, using its ARM64 native library
`libnative-lib_sg_en_2.so`.

```text
APK SHA-256: 3f2d9846ef84477aa18789ff1710a9a6a839193459597ec96bd7167b87924136
```

| Setting | Value |
| --- | --- |
| Primary API | `https://<region>.myaqsh.com:9401` |
| App ID | `aaagg10006` |
| `flag` / `app_flag` | `70` |
| Login protocol `version` | `3.3.5` (distinct from the APK version) |
| Encryption index | `22` |

Only the Europe region was tested. Requests use mTLS with the shared
[`client.pem`](custom_components/yqt/core/client.pem) and key passphrase
`yqt-smart-api`, with normal server-certificate verification.

## Signature

```text
SIGN_KEY = JKLDfjiow48fjklsSSDFASDFQPXJKLDKFJ34kfjsdoifjw
sign_flag = aKsdj93kf93jfcdkjaoskjfLAKlWKEJF92lsdLFKkfjsdlfkj
sign = HEX_UPPER(HMAC_SHA256(SIGN_KEY, canonical + "&key=" + SIGN_KEY))
```

1. Add `app_flag=70` and `timestamppp` (Unix milliseconds).
2. Exclude `sign`, `sign_flag`, `encrypted_aes_key`, and `encrypted_aes_iv`
   from signing. Keep `app_flag` in the signed fields.
3. Sort parameter names and join `name=URLENCODE(value)` pairs with `&`.
   Preserve `A–Z a–z 0–9 - _ . ! ~ * ' ( )`, use uppercase percent escapes,
   and encode spaces as `%20`.
4. Compute `sign` using the formula above.
5. Include both `sign` and the exact `sign_flag` above in the inner JSON.

The flag is required in the body but excluded from the HMAC input. Omitting
it or signing it produces `status=-3`, `message="sign error"`.

Canonical values are URL-encoded; inner JSON values remain raw. For example,
`loginname` contains `@` in JSON and `%40` in the canonical string. Known
parameter names are ASCII; null handling and non-ASCII sorting are unverified.

## Encrypted envelope

Encrypt the signed inner JSON as UTF-8 using AES-128-CBC with PKCS#7 padding.
These constants are hex-encoded binary values:

```text
KEY = d95337bb49ea14f4d47bcd36f777c07e
IV  = 0dd9444f8132b092373afd8c74629fed
```

POST the envelope as JSON with `X-Encrypt-Index: 22`:

```json
{"encryptIndex":22,"encryptData":"<uppercase hexadecimal ciphertext>"}
```

GET uses the envelope fields as query parameters. Wire index 22 corresponds to native AES index 21.
Unlike the [YQT POST transport](REVERSE_ENGINEERING.md#encrypted-envelope),
this variant does not percent-encode inner values after signing.

Successful and credential-error JSON responses use the same encryption
envelope. Signature and decryption errors return plain JSON.

## Login

Endpoint: `POST /app/public/S10APP/v2_new_userLogin2`.

Inner fields, before adding `sign`:

```text
app_flag=70, appid=aaagg10006, flag=70, isIPHONE=1, language=enUS,
loginname, newpassword, password, sign_flag=<value above>,
timestamppp=<epoch milliseconds>, version=3.3.5
```

The `password` field is `SHA256_hex(MD5_hex(password))`, with lowercase
hexadecimal output at each step. The additional `newpassword` field uses:

```text
AES_login = AES-128-CBC/PKCS7(loginname, CRED_KEY, CRED_IV)
combined = AES_login || MD5(password)  # raw 16-byte digest
newpassword = HEX_UPPER(SHA256(combined)) + XOR_CHECKSUM
XOR_CHECKSUM = two uppercase hex digits, XOR of every byte of combined

CRED_KEY = 87fe6ba20a09adc5ef5183ac26cf509b
CRED_IV  = 125648f3f4f79c928d6fd7145ca6100a
```

Credential keys are also hex-encoded binary values. Native strings use JNI
Modified UTF-8; the client accepts ASCII credentials without NUL only. Whether
the server requires or validates `newpassword` is unverified.

## Verification

[`tests/test_setracker2.py`](tests/test_setracker2.py) checks native crypto
vectors, signing exclusions, request/response handling, and YQT defaults.

```bash
uv run --with cryptography python -m unittest discover -s tests -p test_setracker2.py
./yqt_client.py --protocol setracker2 --region europe --account YOUR_EMAIL --password YOUR_PASSWORD login
```

Observed live results:

| Request | Response |
| --- | --- |
| HMAC with the required body flag excluded from signing | Encrypted `status=2` credential error |
| Missing flag, flag included in HMAC input, or invalid HMAC | Plain `status=-3`, `sign error` |
| Existing YQT signature with `sign_flag=KHDIW` included in signing | Encrypted `status=2` credential error |
| YQT signature without its flag, or invalid YQT signature | Plain `status=-3`, `sign error` |
| Invalid ciphertext | Plain `status=-5`, `Request decryption failed.` |

Account checks also verified login (`status=1`), encrypted GET responses,
session-bound requests, device discovery through the metadata fallback, and
last-position results including empty responses. Multipart chat sending is
unsupported; other commands and regions need separate validation.

Additional endpoint details remain unverified: a public `v2_findAlarmInfo`
alias, `ry_findDidRoomCountInfo` device counters, and per-query `type` values.
The existing YQT alarm-history path uses `/app/{sid}/S10APP/`; a public alias
or clock-list interpretation has not been established.
