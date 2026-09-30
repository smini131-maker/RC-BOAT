from __future__ import annotations

import keyring

SERVICE = "RCBoatControl"


def _account(host: str, username: str) -> str:
    return f"{username}@{host}"


def load_password(host: str, username: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, _account(host, username))
    except Exception:
        return None


def save_password(host: str, username: str, password: str) -> None:
    keyring.set_password(SERVICE, _account(host, username), password)


def delete_password(host: str, username: str) -> None:
    try:
        keyring.delete_password(SERVICE, _account(host, username))
    except keyring.errors.PasswordDeleteError:
        pass
