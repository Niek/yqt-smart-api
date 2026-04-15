from __future__ import annotations

import argparse
import json
from pathlib import Path

from custom_components.yqt.core.protocol import (
    DEFAULT_LANGUAGE,
    REGIONS,
    YQTError,
    YQTResponseError,
    photo_wall_filename,
    split_dids,
)
from custom_components.yqt.core.sync_client import YQTClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe the YQT SMART HTTP API.")
    parser.add_argument("--region", default="europe", choices=sorted(REGIONS))
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument(
        "--account",
        "--loginname",
        dest="account",
        help="Account identifier for commands that need authentication",
    )
    parser.add_argument("--password", help="Raw account password for commands that need authentication")
    parser.add_argument("--sid", help="Existing session id; skips login for session-bound commands")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("login", help="Log in and print the raw response.")

    devices_parser = subparsers.add_parser("devices", help="List devices for the current user.")
    devices_parser.add_argument("--user-id", type=int, help="Optional user id; defaults to the first id from login.")
    devices_parser.add_argument("--type", dest="device_type", type=int, default=0)

    meta_parser = subparsers.add_parser("device-list-meta", help="Fetch total_did metadata by user.")
    meta_parser.add_argument("--user-id", type=int, help="Optional user id; defaults to the first id from login.")

    send_order_parser = subparsers.add_parser("send-order", help="Send a raw v2_sendOrder command.")
    send_order_parser.add_argument("--sendurl", required=True)

    fresh_position_parser = subparsers.add_parser("fresh-position", help="Trigger a fresh location update for one device.")
    fresh_position_parser.add_argument("--did", required=True)
    fresh_position_parser.add_argument("--model", default="")

    position_parser = subparsers.add_parser("last-position", help="Fetch last known position for one device.")
    position_parser.add_argument("--did", required=True)
    position_parser.add_argument("--did-id", default="")
    position_parser.add_argument("--position-id", default="")

    positions_parser = subparsers.add_parser("last-positions", help="Fetch last known positions for multiple devices.")
    positions_parser.add_argument("--dids", help="Comma-separated did list; defaults to all known devices after login.")
    positions_parser.add_argument("--position-id", default="")

    photowall_parser = subparsers.add_parser("photowall-list", help="List Photo Wall images for one device.")
    photowall_parser.add_argument("--did", required=True)
    photowall_parser.add_argument("--max-id", type=int, default=0)

    photowall_download_parser = subparsers.add_parser("photowall-download", help="Download one Photo Wall image.")
    photowall_download_parser.add_argument("--did", required=True)
    photowall_source = photowall_download_parser.add_mutually_exclusive_group(required=True)
    photowall_source.add_argument("--filename")
    photowall_source.add_argument("--path")
    photowall_download_parser.add_argument(
        "--output",
        help="Output file path; defaults to the remote filename in the current directory.",
    )

    chat_read_parser = subparsers.add_parser("chat-read", help="Read one-to-one chat history for one device.")
    chat_read_parser.add_argument("--did", required=True)
    chat_read_parser.add_argument("--did-id", default="")
    chat_read_parser.add_argument("--user-id", type=int, help="Optional user id; defaults to the first id from login.")
    chat_read_parser.add_argument("--create-time", default="")

    chat_send_parser = subparsers.add_parser("chat-send", help="Send one text chat message to one device.")
    chat_send_parser.add_argument("--did", required=True)
    chat_send_parser.add_argument("--did-id", default="")
    chat_send_parser.add_argument("--user-id", type=int, help="Optional user id; defaults to the first id from login.")
    chat_send_parser.add_argument("--message", required=True)

    alarms_parser = subparsers.add_parser("alarms", help="Fetch alarm history for one device.")
    alarms_parser.add_argument("--did", required=True)
    alarms_parser.add_argument("--did-id", default="")
    alarms_parser.add_argument("--flag", type=int, default=0)
    alarms_parser.add_argument("--count", type=int, default=20)
    alarms_parser.add_argument("--createtime", default="")

    switches_parser = subparsers.add_parser("switches", help="Fetch device switch status.")
    switches_parser.add_argument("--did", required=True)
    switches_parser.add_argument("--did-id", default="")

    return parser


def _require_login_fields(args: argparse.Namespace) -> tuple[str, str]:
    if not args.account or not args.password:
        raise SystemExit("--account and --password are required for this command")
    return args.account, args.password


def _primary_user_id(login_response: dict[str, object]) -> int:
    users = login_response.get("data") or []
    if not users:
        raise SystemExit("login succeeded but no user list was returned")
    user_id = users[0].get("id")
    if not isinstance(user_id, int):
        raise SystemExit("login response did not include a numeric user id")
    return user_id


def _resolve_output_path(output: str | None, filename: str) -> Path:
    if output:
        target = Path(output).expanduser()
        if target.exists() and target.is_dir():
            return target / filename
        return target
    return Path(filename)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    client = YQTClient(region=args.region, language=args.language, session_id=args.sid)

    if args.command == "login":
        loginname, password = _require_login_fields(args)
        response = client.login(loginname, password)
        print(json.dumps(response, indent=2, sort_keys=True))
        return

    if args.command in {"devices", "device-list-meta"}:
        loginname, password = _require_login_fields(args)
        login_response = client.login(loginname, password)
        user_id = args.user_id if args.user_id is not None else _primary_user_id(login_response)
        if args.command == "devices":
            response = client.list_devices(user_id, loginname, device_type=args.device_type)
        else:
            response = client.find_device_list_by_user_id(user_id, loginname)
        print(json.dumps(response, indent=2, sort_keys=True))
        return

    account: str | None = client.loginname or args.account

    if not client.session_id:
        account, password = _require_login_fields(args)
        client.login(account, password)
    elif args.account:
        account = args.account

    if args.command == "last-position":
        _, did_id = client.resolve_device(args.did, args.did_id)
        response = client.find_last_position(
            did=args.did,
            did_id=did_id,
            position_id=args.position_id,
        )
    elif args.command == "send-order":
        response = client.send_order(sendurl=args.sendurl)
    elif args.command == "fresh-position":
        response = client.fresh_position(did=args.did, model=args.model)
    elif args.command == "last-positions":
        dids = split_dids(args.dids or ",".join(client.known_dids()))
        if not dids:
            raise SystemExit("--dids is required unless device metadata is available from login")
        response = client.find_last_positions(dids, position_id=args.position_id)
    elif args.command == "photowall-list":
        response = client.find_photo_wall_info(did=args.did, max_id=args.max_id)
    elif args.command == "photowall-download":
        filename = photo_wall_filename(args.path or args.filename)
        raw = client.download_photo_wall(did=args.did, filename=filename)
        output_path = _resolve_output_path(args.output, filename).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(raw)
        response = {
            "status": 1,
            "message": "download ok",
            "did": args.did,
            "filename": filename,
            "bytes": len(raw),
            "output": str(output_path),
        }
    elif args.command == "chat-read":
        _, did_id = client.resolve_device(args.did, args.did_id)
        response = client.find_talk_new_info(
            did=args.did,
            did_id=did_id,
            user_id=args.user_id,
            create_time=args.create_time,
        )
    elif args.command == "chat-send":
        _, did_id = client.resolve_device(args.did, args.did_id)
        response = client.send_talk_message(
            did=args.did,
            did_id=did_id,
            user_id=args.user_id,
            loginname=account,
            message=args.message,
        )
    elif args.command == "alarms":
        _, did_id = client.resolve_device(args.did, args.did_id)
        response = client.find_alarm_info(
            did=args.did,
            did_id=did_id,
            flag=args.flag,
            count=args.count,
            createtime=args.createtime,
        )
    elif args.command == "switches":
        _, did_id = client.resolve_device(args.did, args.did_id)
        response = client.find_device_switch(did=args.did, did_id=did_id)
    else:
        raise SystemExit(f"unsupported command: {args.command}")

    print(json.dumps(response, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except YQTResponseError as exc:
        print(json.dumps(exc.payload, indent=2, sort_keys=True))
        raise SystemExit(1) from exc
    except YQTError as exc:
        raise SystemExit(str(exc)) from exc
