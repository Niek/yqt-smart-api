# YQT Smart Reverse Engineering

This repository is an unofficial reverse-engineering project for YQT kid watches and related white-label apps such as YQT Smart, SeTracker, SeTracker 2, and CarePro+.

It currently contains two practical outputs:

- a standalone Python client for probing the backend and testing commands
- a Home Assistant custom integration under `custom_components/yqt`

For protocol notes and endpoint findings, see `REVERSE_ENGINEERING.md`.

## Standalone Client

The CLI entry point is:

```bash
python3 yqt_client.py --region europe --account YOUR_EMAIL --password YOUR_PASSWORD login
```

Useful smoke tests:

```bash
python3 yqt_client.py --region europe --account YOUR_EMAIL --password YOUR_PASSWORD devices
python3 yqt_client.py --region europe --account YOUR_EMAIL --password YOUR_PASSWORD last-position --did YOUR_DEVICE_ID
python3 yqt_client.py --region europe --account YOUR_EMAIL --password YOUR_PASSWORD fresh-position --did YOUR_DEVICE_ID
```

If you want to see the available commands:

```bash
python3 yqt_client.py --help
```

## Home Assistant

The Home Assistant integration lives in:

```text
custom_components/yqt
```

To install it in Home Assistant:

1. Copy `custom_components/yqt` into your HA config directory under `custom_components/yqt`.
2. Restart Home Assistant.
3. In Home Assistant, go to `Settings -> Devices & services -> Add integration`.
4. Search for `YQT Smart`.
5. Enter your `region`, `account`, and `password`.

The current MVP exposes:

- one device per watch
- a `device_tracker` with the last known position
- battery and last-fix sensors
- a stale-location binary sensor
- a button to request a fresh location update

## Notes

- This is unofficial and may break if the vendor changes the backend.
- The shared protocol logic lives in `custom_components/yqt/core/` and is used by both the CLI and the Home Assistant integration.
