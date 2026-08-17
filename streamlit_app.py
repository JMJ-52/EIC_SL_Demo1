"""Entry point for the independent Streamlit EIC demo."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path


_ACTIVE_VIEW_KEY = "_active_view"


def required_secret_names() -> tuple[str, ...]:
    """Return the names expected in Streamlit Cloud Secrets."""

    return (
        "GUEST_USERNAME", "GUEST_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD",
        "OPENAI_API_KEY", "OPENAI_MODEL",
        "TAVILY_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "REQUEST_RECIPIENT_EMAIL",
    )


def reset_session(
    state: MutableMapping[str, object], *, storage_root: Path | None = None,
) -> None:
    """Delete this session's uploads, then discard all session-only demo state.

    Cleanup is deliberately delegated to the validated storage boundary.  If
    cleanup refuses the token or directory, the exception propagates and the
    state is retained so the UI cannot misleadingly report a completed reset.
    """

    from storage import cleanup_session_files, cleanup_stale_session_files, session_storage_root
    from upload_runtime import active_session_tokens, unregister_active_session_token

    token = state.get("_general_upload_session_token")
    if isinstance(token, str):
        cleanup_session_files(token, storage_root or session_storage_root())
    cleanup_stale_session_files(
        storage_root or session_storage_root(),
        excluded_session_tokens=active_session_tokens(),
    )
    if isinstance(token, str):
        unregister_active_session_token(token)
    state.clear()


def cleanup_uploads_on_process_start(*, storage_root: Path | None = None) -> bool:
    """Run one bounded cleanup pass for upload directories left by a prior process."""

    from storage import cleanup_stale_session_files, session_storage_root
    from upload_runtime import run_startup_cleanup

    root = storage_root or session_storage_root()
    return run_startup_cleanup(
        lambda active_tokens: cleanup_stale_session_files(
            root, excluded_session_tokens=active_tokens,
        )
    )


def selected_view_for_role(role: object, requested: object) -> str:
    """Return a closed-set view; guests can never select the admin renderer."""

    if role == "admin" and requested == "admin":
        return "admin"
    return "general"


def main() -> None:
    """Initialize session-only state and route the selected demo role."""

    import streamlit as st
    from auth import require_admin
    from views.admin import render_admin_page
    from views.general import render_general_page
    from ai_demo import AI_ACTION_LIMIT
    from views.landing import render_landing
    from session_store import initialize_state

    st.set_page_config(page_title="EIC 교체 타당성 검토 데모", layout="wide")
    try:
        cleanup_uploads_on_process_start()
    except Exception:
        st.error("이전 세션 업로드를 정리하지 못했습니다. 관리자에게 문의하세요.")
        st.stop()
        return
    st.caption("시연 데이터는 현재 브라우저 세션에만 저장됩니다.")

    initialize_state(st.session_state)
    st.sidebar.warning(
        "세션 전용 데모: 프로젝트·변경 사항·업로드는 영구 저장되지 않습니다."
    )
    ai_actions = st.session_state.get("_ai_action_count", 0)
    if not isinstance(ai_actions, int) or isinstance(ai_actions, bool) or ai_actions < 0:
        ai_actions = 0
    st.sidebar.caption(f"이 세션의 AI 사용량: {ai_actions} / {AI_ACTION_LIMIT}회")
    role = st.session_state.get("role")
    if role is None:
        render_landing(st.session_state, st.secrets)
        return

    if st.sidebar.button("로그아웃 및 세션 초기화"):
        try:
            reset_session(st.session_state)
        except Exception:
            st.error("세션을 정리하지 못했습니다. 잠시 후 다시 시도하세요.")
        else:
            st.rerun()

    if role == "guest":
        st.session_state[_ACTIVE_VIEW_KEY] = "general"
        render_general_page()
        return

    if require_admin(st.session_state):
        labels = {"일반 워크플로": "general", "관리자": "admin"}
        current = selected_view_for_role(role, st.session_state.get(_ACTIVE_VIEW_KEY))
        selected_label = st.sidebar.radio(
            "화면 이동", tuple(labels),
            index=list(labels.values()).index(current), key="_admin_navigation",
        )
        selected = labels[selected_label]
        st.session_state[_ACTIVE_VIEW_KEY] = selected
        if selected == "admin":
            render_admin_page()
        else:
            render_general_page()
        return

    # A malformed or manually altered session never reaches a protected page.
    try:
        reset_session(st.session_state)
    except Exception:
        st.error("세션을 안전하게 정리하지 못했습니다. 잠시 후 다시 시도하세요.")
        st.stop()
        return
    st.warning("관리자 접근 권한이 없어 세션을 초기화했습니다.")
    render_landing(st.session_state, st.secrets)


if __name__ == "__main__":
    main()
