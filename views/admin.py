"""Administrator-only, session-scoped demonstration controls."""

from __future__ import annotations

import json
from collections.abc import MutableMapping, Sequence
from typing import Any

from auth import require_admin
from session_store import (
    approve_user,
    decide_review,
    export_approved_equipment as _export_approved_equipment,
    get_statistics,
    list_activity_logs,
    list_lifecycle_reviews,
    list_login_logs,
    list_projects,
    list_users,
    reject_user,
)


def export_approved_equipment(state: MutableMapping[str, object]) -> bytes:
    """Return the store's safe approved-equipment JSON download bytes."""

    return _export_approved_equipment(state)


def decide_lifecycle_reviews(
    state: MutableMapping[str, object], review_ids: Sequence[str], decision: str,
) -> None:
    """Apply one administrator lifecycle decision per selected review.

    Calling the store once for each ID deliberately preserves a separate audit
    activity record for every individual review decision, including bulk UI
    actions.
    """

    for review_id in review_ids:
        decide_review(state, review_id, decision)


def _render_users(st: Any, state: MutableMapping[str, object]) -> None:
    users = list_users(state)
    st.header("사용자 승인 관리")
    pending = [row for row in users if row.get("status") == "pending"]
    approved = [row for row in users if row.get("status") == "approved"]
    rejected = [row for row in users if row.get("status") == "rejected"]

    st.subheader("승인 대기 사용자")
    if not pending:
        st.caption("승인 대기 사용자가 없습니다.")
    for user in pending:
        user_id = str(user["id"])
        st.write(f"{user.get('name', '')} · {user.get('email', '')}")
        approve, reject = st.columns(2)
        if approve.button("승인", key=f"approve-user-{user_id}"):
            approve_user(state, user_id)
            st.rerun()
        if reject.button("거절", key=f"reject-user-{user_id}"):
            reject_user(state, user_id)
            st.rerun()

    st.subheader("승인 사용자")
    st.dataframe(approved, use_container_width=True, hide_index=True)
    st.subheader("거절 사용자")
    st.dataframe(rejected, use_container_width=True, hide_index=True)


def _render_logs(st: Any, state: MutableMapping[str, object]) -> None:
    st.header("로그")
    st.subheader("로그인 로그")
    st.dataframe(list_login_logs(state), use_container_width=True, hide_index=True)
    st.subheader("활동 로그")
    st.dataframe(list_activity_logs(state), use_container_width=True, hide_index=True)


def _render_statistics(st: Any, state: MutableMapping[str, object]) -> None:
    users = list_users(state)
    statistics = get_statistics(state)
    st.header("프로젝트 및 사용자 통계")
    project_count, user_count, approved_count = st.columns(3)
    project_count.metric("프로젝트", len(list_projects(state)))
    user_count.metric("전체 사용자", len(users))
    approved_count.metric("승인 사용자", sum(row.get("status") == "approved" for row in users))
    st.dataframe([statistics], use_container_width=True, hide_index=True)


def _render_lifecycle_reviews(st: Any, state: MutableMapping[str, object]) -> None:
    reviews = list_lifecycle_reviews(state)
    pending = [row for row in reviews if row.get("status") == "pending"]
    st.header("수명주기 검토 대기열")
    st.caption("일반 화면의 웹 수집 미리보기와 PDF 확인 요청은 이 대기열에 자동 등록되지 않습니다.")
    if not pending:
        st.caption("결정 대기 중인 수명주기 검토가 없습니다.")
        return

    for review in pending:
        review_id = str(review["id"])
        st.write(
            f"{review.get('supplier', '')} · {review.get('model_name', '')} · "
            f"{review.get('target', '')}"
        )
        approve, reject = st.columns(2)
        if approve.button("개별 승인", key=f"approve-review-{review_id}"):
            decide_lifecycle_reviews(state, [review_id], "approved")
            st.rerun()
        if reject.button("개별 거절", key=f"reject-review-{review_id}"):
            decide_lifecycle_reviews(state, [review_id], "rejected")
            st.rerun()

    labels = {
        str(row["id"]): f"{row.get('supplier', '')} · {row.get('model_name', '')}"
        for row in pending
    }
    selected = st.multiselect(
        "일괄 처리할 검토 항목", options=list(labels), format_func=labels.get,
    )
    approve_all, reject_all = st.columns(2)
    if approve_all.button("선택 항목 일괄 승인", key="bulk-approve-reviews") and selected:
        decide_lifecycle_reviews(state, selected, "approved")
        st.rerun()
    if reject_all.button("선택 항목 일괄 거절", key="bulk-reject-reviews") and selected:
        decide_lifecycle_reviews(state, selected, "rejected")
        st.rerun()


def _render_equipment_export(st: Any, state: MutableMapping[str, object]) -> None:
    payload = export_approved_equipment(state)
    approved_rows = json.loads(payload.decode("utf-8"))
    st.header("승인 설비")
    st.dataframe(approved_rows, use_container_width=True, hide_index=True)
    st.download_button(
        "승인 설비 JSON 다운로드", data=payload,
        file_name="approved-equipment.json", mime="application/json",
    )


def render_admin_page() -> None:
    """Render management controls only after the mandatory administrator guard."""

    import streamlit as st

    # This guard intentionally precedes every management data read and widget.
    if not require_admin(st.session_state):
        st.warning("관리자 접근 권한이 없습니다.")
        st.stop()
        return

    state = st.session_state
    st.title("관리자 시연")
    st.warning(
        "세션 전용 데모입니다. 관리자 변경 사항과 다운로드 대상은 영구 저장되지 않으며 "
        "로그아웃 및 세션 초기화 시 삭제됩니다."
    )
    _render_users(st, state)
    _render_logs(st, state)
    _render_statistics(st, state)
    _render_lifecycle_reviews(st, state)
    _render_equipment_export(st, state)
