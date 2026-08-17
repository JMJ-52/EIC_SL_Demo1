from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import views.general as general
from storage import save_uploads
from session_store import (
    add_document_metadata,
    add_equipment,
    create_project,
    create_report_version,
    decide_review,
    delete_equipment,
    export_state,
    get_project,
    get_report_version,
    initialize_state,
    list_documents,
    list_equipment,
    remove_document_metadata,
    transition_project,
    update_equipment,
    update_project,
)


class Upload:
    def __init__(self, name: str, contents: bytes) -> None:
        self.name = name
        self._contents = contents

    def getbuffer(self) -> memoryview:
        return memoryview(self._contents)


def test_project_equipment_document_and_report_version_workflow_uses_public_store_apis() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    project_id = create_project(state, {"investment_code": "EIC-4", "project_name": "신규 검토"})
    update_project(state, project_id, {"description": "현장 수동 등록"})
    transition_project(state, project_id, "confirmed")
    transition_project(state, project_id, "on_hold")
    transition_project(state, project_id, "reviewed")

    equipment_id = add_equipment(
        state,
        project_id,
        {"name": "제어반 D", "equipment_type": "제어반", "manufacturer": "Demo"},
    )
    update_equipment(state, project_id, equipment_id, {"model_name": "D-100", "status": "reviewed"})
    document_id = add_document_metadata(
        state,
        project_id,
        {"name": "source.pdf", "path": "/tmp/eic-sl-demo/session-a/source.pdf", "size_bytes": 4},
    )
    version_id = create_report_version(state, project_id, "수동 검토본")
    delete_equipment(state, project_id, equipment_id)
    remove_document_metadata(state, project_id, document_id)

    project = get_project(state, project_id)
    version = get_report_version(state, version_id)
    exported = export_state(state)

    assert project["status"] == "reviewed"
    assert project["description"] == "현장 수동 등록"
    assert equipment_id not in {row["id"] for row in list_equipment(state, project_id)}
    assert document_id not in {row["id"] for row in list_documents(state, project_id)}
    assert version["project_content"]["equipment"][equipment_id]["model_name"] == "D-100"
    assert exported["activity_logs"][-1]["action"] == "remove_document_metadata"


def test_approved_equipment_is_read_only_in_general_editor_after_admin_decision() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    review_id, review = next(
        (review_id, review)
        for review_id, review in state["lifecycle_reviews"].items()
        if review["status"] == "pending"
    )
    decide_review(state, review_id, "approved")

    class FakeStreamlit:
        info_messages: list[str] = []

        def __init__(self, selected_equipment_id: str) -> None:
            self.selected_equipment_id = selected_equipment_id

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def subheader(self, *args, **kwargs): pass
        def form(self, *args, **kwargs): return self
        def text_input(self, *args, **kwargs): return ""
        def form_submit_button(self, *args, **kwargs): return False
        def dataframe(self, *args, **kwargs): pass

        def selectbox(self, label, options, **kwargs):
            if label == "수정할 설비":
                return next(
                    choice for choice, equipment_id in options.items()
                    if equipment_id == self.selected_equipment_id
                )
            raise AssertionError("approved equipment must not render an editable status")

        def info(self, message):
            self.info_messages.append(message)

        def button(self, *args, **kwargs):
            raise AssertionError("approved equipment must not expose delete controls")

    st = FakeStreamlit(str(review["equipment_id"]))
    general._render_equipment(st, state, str(review["project_id"]))

    assert st.info_messages == ["관리자가 승인한 설비는 일반 워크플로에서 수정하거나 삭제할 수 없습니다."]
    assert state["equipment"][review["project_id"]][review["equipment_id"]]["status"] == "approved"


def test_project_deletion_removes_only_its_exact_current_session_uploads(tmp_path: Path) -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    project_id = create_project(state, {"project_name": "delete uploads"})
    session_token = "current-session"
    state["_general_upload_session_token"] = session_token
    uploads = save_uploads(
        [Upload("one.pdf", b"one"), Upload("two.xlsx", b"two")],
        session_token,
        tmp_path,
    )
    for upload in uploads:
        add_document_metadata(state, project_id, upload.document_metadata())
    same_session_keep = tmp_path / session_token / "keep.pptx"
    same_session_keep.write_bytes(b"keep")
    other_session = tmp_path / "other-session"
    other_session.mkdir()
    other_keep = other_session / "keep.pdf"
    other_keep.write_bytes(b"other")

    general._delete_project_with_uploads(state, project_id, session_token, tmp_path)

    assert project_id not in state["projects"]
    assert all(not upload.path.exists() for upload in uploads)
    assert same_session_keep.read_bytes() == b"keep"
    assert other_keep.read_bytes() == b"other"


def test_project_deletion_prevalidates_all_paths_before_mutating_files_or_metadata(
    tmp_path: Path,
) -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    project_id = create_project(state, {"project_name": "reject foreign path"})
    session_token = "current-session"
    state["_general_upload_session_token"] = session_token
    upload = save_uploads([Upload("keep.pdf", b"keep")], session_token, tmp_path)[0]
    add_document_metadata(state, project_id, upload.document_metadata())
    foreign_directory = tmp_path / "other-session"
    foreign_directory.mkdir()
    foreign = foreign_directory / "foreign.pdf"
    foreign.write_bytes(b"foreign")
    add_document_metadata(
        state,
        project_id,
        {"name": "foreign.pdf", "path": str(foreign), "size_bytes": 7},
    )

    with pytest.raises(ValueError, match="outside this session"):
        general._delete_project_with_uploads(state, project_id, session_token, tmp_path)

    assert project_id in state["projects"]
    assert upload.path.read_bytes() == b"keep"
    assert foreign.read_bytes() == b"foreign"


@pytest.mark.parametrize(
    ("outcome", "expected_method"),
    (
        (SimpleNamespace(succeeded=["equipment"], failed=[], warnings=[]), "successes"),
        (
            SimpleNamespace(succeeded=["equipment"], failed=[], warnings=["detail warning"]),
            "warnings",
        ),
    ),
)
def test_re_review_submit_renders_returned_success_or_warning_outcome(
    monkeypatch: pytest.MonkeyPatch, outcome: object, expected_method: str,
) -> None:
    state: dict[str, object] = {"_ai_action_count": 0}

    class FakeStreamlit:
        secrets: dict[str, str] = {}

        def __init__(self) -> None:
            self.successes: list[str] = []
            self.warnings: list[str] = []
            self.captions: list[str] = []

        def __enter__(self): return self
        def __exit__(self, *args): return False
        def subheader(self, *args, **kwargs): pass
        def caption(self, message): self.captions.append(message)
        def button(self, *args, **kwargs): return False
        def form(self, *args, **kwargs): return self
        def text_area(self, *args, **kwargs): return "updated conditions"
        def form_submit_button(self, *args, **kwargs): return True
        def success(self, message): self.successes.append(message)
        def warning(self, message): self.warnings.append(message)
        def error(self, message): raise AssertionError(message)

    monkeypatch.setattr(general, "re_review_project", lambda *args, **kwargs: outcome)
    st = FakeStreamlit()

    general._render_ai_actions(st, state, "project-id")

    assert getattr(st, expected_method)
    if expected_method == "successes":
        assert st.successes == ["이전 보고서를 보존하고 재검토를 완료했습니다."]
    else:
        assert not st.successes
        assert "세부 실패 1건" in st.warnings[0]
