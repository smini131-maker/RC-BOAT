#!/usr/bin/env python3
"""Create the Jetson-only NTRIP EnvironmentFile without echoing the password."""
import getpass
import json
import os
from pathlib import Path


FIELDS = (
    "RCBOAT_NTRIP_ENABLED",
    "RCBOAT_NTRIP_HOST",
    "RCBOAT_NTRIP_PORT",
    "RCBOAT_NTRIP_MOUNTPOINT",
    "RCBOAT_NTRIP_USERNAME",
    "RCBOAT_NTRIP_PASSWORD",
    "RCBOAT_NTRIP_TLS",
)


def load_env_file(path):
    values = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key not in FIELDS:
            continue
        try:
            values[key] = str(json.loads(value.strip()))
        except (TypeError, ValueError, json.JSONDecodeError):
            values[key] = value.strip().strip("\"'")
    return values


def write_env_file(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        key + "=" + json.dumps(str(values.get(key, ""))) + "\n"
        for key in FIELDS
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def prompt(label, current="", required=True):
    suffix = f" [{current}]" if current else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        value = value or current
        if value or not required:
            return value
        print(f"{label} is required.")


def main():
    if os.geteuid() == 0:
        raise SystemExit("Run this as the jetson account, not root.")
    path = Path.home() / "rcboat_balloon_data" / "ntrip.env"
    current = load_env_file(path)
    print("NTRIP values are stored only on this Jetson. The password is never displayed.")
    host = prompt("Host", current.get("RCBOAT_NTRIP_HOST", ""))
    port = prompt("Port", current.get("RCBOAT_NTRIP_PORT", "2101"))
    mountpoint = prompt("Mount Point", current.get("RCBOAT_NTRIP_MOUNTPOINT", ""))
    username = prompt("Username", current.get("RCBOAT_NTRIP_USERNAME", ""))
    password = getpass.getpass("Password [Enter keeps the saved password]: ")
    password = password or current.get("RCBOAT_NTRIP_PASSWORD", "")
    if not password:
        raise SystemExit("Password is required for the first setup.")
    tls_default = current.get("RCBOAT_NTRIP_TLS", "false").lower() == "true"
    tls_answer = input(f"TLS (y/N) [{'y' if tls_default else 'N'}]: ").strip().lower()
    tls = tls_default if not tls_answer else tls_answer in {"y", "yes", "1", "true"}
    values = {
        "RCBOAT_NTRIP_ENABLED": "true",
        "RCBOAT_NTRIP_HOST": host,
        "RCBOAT_NTRIP_PORT": str(int(port)),
        "RCBOAT_NTRIP_MOUNTPOINT": mountpoint.lstrip("/"),
        "RCBOAT_NTRIP_USERNAME": username,
        "RCBOAT_NTRIP_PASSWORD": password,
        "RCBOAT_NTRIP_TLS": str(tls).lower(),
    }
    write_env_file(path, values)
    print(f"Saved {path} with mode 0600.")
    print("Restart rcboat_balloon_ros.service, or stop and relaunch roslaunch, to load it now.")


if __name__ == "__main__":
    main()
