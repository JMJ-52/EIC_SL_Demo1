from auth import authenticate_admin, authenticate_guest, enter_admin, enter_guest, require_admin
import sys

import pytest

from session_store import initialize_state
from views.landing import render_landing


def test_admin_authentication_requires_both_secret_values() -> None:
    secrets = {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "correct"}

    assert authenticate_admin("admin", "correct", secrets) is True
    assert authenticate_admin("admin", "wrong", secrets) is False
    assert authenticate_admin("wrong", "correct", secrets) is False


def test_guest_authentication_requires_both_guest_secret_values() -> None:
    secrets = {"GUEST_USERNAME": "guest", "GUEST_PASSWORD": "correct"}

    assert authenticate_guest("guest", "correct", secrets) is True
    assert authenticate_guest("guest", "wrong", secrets) is False
    assert authenticate_guest("wrong", "correct", secrets) is False


def test_guest_and_admin_credentials_are_separate() -> None:
    secrets = {
        "GUEST_USERNAME": "guest",
        "GUEST_PASSWORD": "guest-password",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "admin-password",
    }

    assert authenticate_guest("admin", "admin-password", secrets) is False
    assert authenticate_admin("guest", "guest-password", secrets) is False


def test_guest_cannot_pass_admin_guard() -> None:
    assert require_admin({"role": "guest"}) is False
    assert require_admin({"role": "admin"}) is True


def test_missing_or_non_string_secret_values_cannot_authenticate() -> None:
    assert authenticate_admin("admin", "correct", {}) is False
    assert authenticate_admin("admin", "correct", {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": None}) is False
    assert authenticate_admin(None, "correct", {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "correct"}) is False
    assert authenticate_guest("guest", "correct", {}) is False
    assert authenticate_guest("guest", "correct", {"GUEST_USERNAME": "guest", "GUEST_PASSWORD": None}) is False


def test_role_transitions_only_assign_valid_roles() -> None:
    state: dict[str, object] = {"other": "retained", "role": "unexpected"}

    enter_guest(state)
    assert state == {"other": "retained", "role": "guest"}
    enter_admin(state)
    assert state == {"other": "retained", "role": "admin"}


def test_successful_admin_login_is_logged_and_widget_credentials_are_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RerunCalled(Exception):
        pass

    class Form:
        def __enter__(self): return self
        def __exit__(self, *args): return None

    class FakeStreamlit:
        @staticmethod
        def title(*args, **kwargs): return None
        @staticmethod
        def form(*args, **kwargs): return Form()
        @staticmethod
        def text_input(label, **kwargs):
            return "admin" if "ID" in label else "correct"
        @staticmethod
        def form_submit_button(*args, **kwargs): return True
        @staticmethod
        def error(*args, **kwargs): raise AssertionError("login should succeed")
        @staticmethod
        def rerun(): raise RerunCalled()

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit)
    state: dict[str, object] = {
        "admin_username": "admin", "admin_password": "correct", "admin_login_open": True,
    }
    initialize_state(state)

    with pytest.raises(RerunCalled):
        render_landing(state, {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "correct"})

    assert state["role"] == "admin"
    assert "admin_username" not in state and "admin_password" not in state
    assert state["login_logs"][-1]["user_id"] == "admin"
    assert state["login_logs"][-1]["outcome"] == "success"
