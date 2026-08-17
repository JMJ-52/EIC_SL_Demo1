"""The initial role selection and administrator-login screen."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping

from auth import authenticate_admin, authenticate_guest, enter_admin, enter_guest
from session_store import append_login_log


_ADMIN_PASSWORD_WIDGET_KEY = "admin_password"
_ADMIN_LOGIN_OPEN_KEY = "admin_login_open"
_GUEST_PASSWORD_WIDGET_KEY = "guest_password"
_GUEST_LOGIN_OPEN_KEY = "guest_login_open"


def render_landing(state: MutableMapping[str, object], secrets: Mapping[str, object]) -> None:
    """Render exactly the guest and administrator entry choices initially."""

    import streamlit as st

    st.title("EIC 교체 타당성 검토 데모")
    if state.get(_GUEST_LOGIN_OPEN_KEY) is True:
        _render_guest_login(state, secrets)
        return

    if state.get(_ADMIN_LOGIN_OPEN_KEY) is not True:
        if st.button("초대 이용자", use_container_width=True):
            state[_GUEST_LOGIN_OPEN_KEY] = True
            st.rerun()
        if st.button("관리자", use_container_width=True):
            state[_ADMIN_LOGIN_OPEN_KEY] = True
            st.rerun()
        return

    with st.form("admin_login"):
        username = st.text_input("관리자 ID", key="admin_username")
        password = st.text_input("비밀번호", type="password", key=_ADMIN_PASSWORD_WIDGET_KEY)
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        authenticated = authenticate_admin(username, password, secrets)
        state.pop(_ADMIN_PASSWORD_WIDGET_KEY, None)
        state.pop("admin_username", None)
        if authenticated:
            enter_admin(state)
            append_login_log(state, "admin", "success")
            state.pop(_ADMIN_LOGIN_OPEN_KEY, None)
            st.rerun()
        else:
            st.error("관리자 인증에 실패했습니다.")


def _render_guest_login(state: MutableMapping[str, object], secrets: Mapping[str, object]) -> None:
    """Render the guest form and grant the general-only role after authentication."""

    import streamlit as st

    with st.form("guest_login"):
        username = st.text_input("초대 이용자 ID", key="guest_username")
        password = st.text_input("비밀번호", type="password", key=_GUEST_PASSWORD_WIDGET_KEY)
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        authenticated = authenticate_guest(username, password, secrets)
        state.pop(_GUEST_PASSWORD_WIDGET_KEY, None)
        state.pop("guest_username", None)
        if authenticated:
            enter_guest(state)
            append_login_log(state, "guest", "success")
            state.pop(_GUEST_LOGIN_OPEN_KEY, None)
            st.rerun()
        else:
            st.error("초대 이용자 인증에 실패했습니다.")


def logout(state: MutableMapping[str, object]) -> None:
    """End the selected role and discard the password widget value."""

    state.pop("role", None)
    state.pop(_ADMIN_PASSWORD_WIDGET_KEY, None)
    state.pop("admin_username", None)
    state.pop(_ADMIN_LOGIN_OPEN_KEY, None)
    state.pop(_GUEST_PASSWORD_WIDGET_KEY, None)
    state.pop("guest_username", None)
    state.pop(_GUEST_LOGIN_OPEN_KEY, None)
