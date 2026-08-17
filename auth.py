"""Role and administrator authentication helpers for the demo session."""

from __future__ import annotations

import hmac
from collections.abc import Mapping, MutableMapping
from typing import Literal


Role = Literal["guest", "admin"]


def authenticate_guest(username: object, password: object, secrets: Mapping[str, object]) -> bool:
    """Return whether both supplied guest credentials match the injected secrets."""

    configured_username = secrets.get("GUEST_USERNAME")
    configured_password = secrets.get("GUEST_PASSWORD")
    if not all(isinstance(value, str) for value in (
        username, password, configured_username, configured_password,
    )):
        return False

    return hmac.compare_digest(username, configured_username) & hmac.compare_digest(
        password, configured_password,
    )


def authenticate_admin(username: object, password: object, secrets: Mapping[str, object]) -> bool:
    """Return whether both supplied credentials match the injected secrets.

    Configuration and credential type errors deliberately have the same false
    result as an ordinary authentication failure.
    """

    configured_username = secrets.get("ADMIN_USERNAME")
    configured_password = secrets.get("ADMIN_PASSWORD")
    if not all(isinstance(value, str) for value in (
        username, password, configured_username, configured_password,
    )):
        return False

    return hmac.compare_digest(username, configured_username) & hmac.compare_digest(
        password, configured_password,
    )


def enter_guest(state: MutableMapping[str, object]) -> None:
    """Set the session to the valid guest role."""

    state["role"] = "guest"


def enter_admin(state: MutableMapping[str, object]) -> None:
    """Set the session to the valid administrator role."""

    state["role"] = "admin"


def require_admin(state: Mapping[str, object]) -> bool:
    """Return true only when the session has the administrator role."""

    return state.get("role") == "admin"
