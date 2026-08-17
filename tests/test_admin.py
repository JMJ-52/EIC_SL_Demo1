import json
import sys

import pytest

from views.admin import decide_lifecycle_reviews, export_approved_equipment, render_admin_page
from session_store import add_equipment, approve_user, initialize_state, update_equipment


def test_approval_updates_user_and_appends_activity_log() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    user_id = next(user_id for user_id, user in state["users"].items() if user["status"] == "pending")

    approve_user(state, user_id)

    assert state["users"][user_id]["status"] == "approved"
    assert state["activity_logs"][-1]["action"] == "approve_user"


def test_export_approved_equipment_returns_json_bytes() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    payload = export_approved_equipment(state)

    assert isinstance(payload, bytes)
    assert isinstance(json.loads(payload.decode("utf-8")), list)


def test_export_includes_exactly_approved_equipment_not_reviewed_or_confirmed() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    approved_id = add_equipment(state, project_id, {"name": "approved", "status": "approved"})
    reviewed_id = add_equipment(state, project_id, {"name": "reviewed", "status": "reviewed"})
    confirmed_id = add_equipment(state, project_id, {"name": "confirmed", "status": "confirmed"})

    payload = export_approved_equipment(state)
    rows = json.loads(payload.decode("utf-8"))

    assert isinstance(payload, bytes)
    assert [row["id"] for row in rows] == [approved_id]
    assert {reviewed_id, confirmed_id}.isdisjoint({row["id"] for row in rows})
    assert {row["status"] for row in rows} == {"approved"}


def test_guest_guard_denies_and_stops_before_reading_management_data(monkeypatch: pytest.MonkeyPatch) -> None:
    class StopCalled(Exception):
        pass

    class FakeStreamlit:
        session_state = {"role": "guest"}
        warnings: list[str] = []

        @classmethod
        def warning(cls, message: str) -> None:
            cls.warnings.append(message)

        @staticmethod
        def stop() -> None:
            raise StopCalled()

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit)

    with pytest.raises(StopCalled):
        render_admin_page()

    assert FakeStreamlit.warnings == ["관리자 접근 권한이 없습니다."]


def test_lifecycle_single_and_bulk_decisions_use_store() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    first_id = next(iter(state["lifecycle_reviews"]))
    second_id = "second-pending-review"
    state["lifecycle_reviews"][second_id] = {
        "id": second_id, "supplier": "Demo", "model_name": "X-1", "target": "Drive",
        "status": "pending", "decision": None, "decided_at": None,
    }
    before = len(state["activity_logs"])

    decide_lifecycle_reviews(state, [first_id], "approved")
    decide_lifecycle_reviews(state, [second_id], "rejected")

    assert state["lifecycle_reviews"][first_id]["status"] == "approved"
    assert state["lifecycle_reviews"][second_id]["status"] == "rejected"
    assert [row["action"] for row in state["activity_logs"][before:]] == [
        "decide_review", "decide_review",
    ]


def test_reachable_review_approval_populates_strict_equipment_export() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    review_id, review = next(
        (row_id, row) for row_id, row in state["lifecycle_reviews"].items()
        if row["status"] == "pending"
    )

    decide_lifecycle_reviews(state, [review_id], "approved")

    rows = json.loads(export_approved_equipment(state).decode("utf-8"))
    approved = next(row for row in rows if row["id"] == review["equipment_id"])
    assert approved["project_id"] == review["project_id"]
    assert approved["status"] == "approved"


def test_export_filters_to_safe_approved_equipment_fields() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    equipment_id = add_equipment(
        state,
        project_id,
        {
            "name": "안전한 설비", "equipment_type": "Drive", "status": "approved",
            "password": "do-not-export", "role": "admin", "path": "/tmp/upload.pdf",
            "report": {"secret_key": "hidden", "upload_path": "/tmp/report.pdf", "score": 91},
        },
    )
    update_equipment(state, project_id, equipment_id, {"upload_path": "/tmp/also-private"})

    rows = json.loads(export_approved_equipment(state).decode("utf-8"))
    exported = next(row for row in rows if row["id"] == equipment_id)

    assert set(exported).issubset({
        "id", "project_id", "name", "equipment_type", "manufacturer", "model_name", "status", "report",
    })
    assert {"password", "role", "path", "upload_path"}.isdisjoint(exported)
    assert exported["report"] == {"score": 91}
    assert exported["status"] == "approved"
