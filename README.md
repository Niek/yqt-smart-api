# YQT Smart Reverse Engineering

This repository is an unofficial reverse-engineering project for YQT kid watches and related white-label apps such as YQT Smart, SeTracker, SeTracker 2, and CarePro+.

It currently contains two practical outputs:

- a standalone Python client for probing the backend and testing commands
- a Home Assistant custom integration under `custom_components/yqt`

For protocol notes and endpoint findings, see `REVERSE_ENGINEERING.md`.

## Compatible Smart Watches

Confirmed examples:

- FREEBOT `T53` ([Amazon](https://www.amazon.com/FREEBOT-Parental-Controls-Emergency-Birthday/dp/B0DRBPY8QC?th=1&linkCode=ll2&tag=nivadema-20&language=en_US&ref_=as_li_ss_tl))
- PTHTECHUS `PTH-G4-S02` ([Amazon](https://www.amazon.com/dp/B09198QYX8?th=1&linkCode=ll2&tag=nivadema-20&language=en_US&ref_=as_li_ss_tl))
- PTHTECHUS `PTH-G4-S07` ([Amazon](https://www.amazon.com/dp/B0B12MC8FP?th=1&linkCode=ll2&tag=nivadema-20&language=en_US&ref_=as_li_ss_tl))
- Tixpc `G31` ([Amazon](https://www.amazon.com/dp/B0DJVSDGT5?th=1&linkCode=ll2&tag=nivadema-20&language=en_US&ref_=as_li_ss_tl))
- tykjszgs `LT31` ([Amazon](https://www.amazon.com/dp/B0CZ6G69WY?th=1&linkCode=ll2&tag=nivadema-20&language=en_US&ref_=as_li_ss_tl))
- `GTQ68NO` ([montre-enfant.com](https://www.montre-enfant.com/produit/traceur-gps-enfant-4g-avec-bouton-d-appel-sos-modele-gtq68no))

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

### HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Niek&repository=yqt-smart-api)

1. In HACS, add this repository as a custom repository with category `Integration`.
2. Install `YQT Smart`.
3. Restart Home Assistant.

### Manual

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
