"""Final security regressions for the independent, session-only demo."""

from __future__ import annotations

import ast
import importlib
import json
import os
from pathlib import Path

import pytest
import streamlit_app
import upload_runtime

from auth import authenticate_admin
from views.admin import export_approved_equipment
from session_store import add_equipment, initialize_state
from streamlit_app import reset_session


APP_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_NAME_FRAGMENTS = {
    "api_key", "credential", "password", "secret", "settings", "smtp_password",
    "tavily_api_key", "token",
}
STREAMLIT_UI_METHODS = {
    "audio", "balloons", "bar_chart", "button", "camera_input", "caption", "chat_input",
    "chat_message", "checkbox", "code", "color_picker", "data_editor", "dataframe",
    "date_input", "download_button", "error", "expander", "file_uploader", "form",
    "form_submit_button", "header", "html", "image", "info", "json", "latex",
    "line_chart", "link_button", "map", "markdown", "metric", "multiselect",
    "navigation", "number_input", "page_link", "pills", "plotly_chart", "popover",
    "progress", "pydeck_chart", "radio", "scatter_chart", "segmented_control", "selectbox",
    "slider", "snow", "status", "subheader", "success", "table", "tabs", "text",
    "text_area", "text_input", "time_input", "title", "toast", "toggle", "vega_lite_chart",
    "video", "warning", "write", "write_stream",
}
SAFE_CREDENTIAL_CONSUMER_CALLS = {
    "_document_bytes", "analyze_project", "answer_equipment_chat", "authenticate_admin",
    "compare_digest", "re_review_project", "save_uploads", "send_pdf_request", "smtp_send_fn",
}
BLOCKED_EXPORT_KEY_FRAGMENTS = (
    "password", "secret", "token", "api_key", "path", "role",
)


def _application_sources() -> list[Path]:
    """Return production Python only, excluding tests and task artifacts."""

    return sorted(
        path for path in APP_ROOT.rglob("*.py")
        if "tests" not in path.parts and ".sdd" not in path.parts
    )


def _names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def _assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_assigned_names(item) for item in node.elts))
    return set()


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _sensitive_names(tree: ast.AST) -> set[str]:
    """Track direct and simply aliased credential values within one module."""

    tainted = {
        name.id for name in ast.walk(tree)
        if isinstance(name, ast.Name)
        and any(fragment in name.id.casefold() for fragment in SENSITIVE_NAME_FRAGMENTS)
    }
    assignments: list[tuple[set[str], ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = set().union(*(_assigned_names(target) for target in node.targets))
            assignments.append((targets, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments.append((_assigned_names(node.target), node.value))
        elif isinstance(node, ast.NamedExpr):
            assignments.append((_assigned_names(node.target), node.value))

    changed = True
    while changed:
        changed = False
        for targets, value in assignments:
            referenced = _names(value)
            if isinstance(value, ast.Call):
                # Only audited boundaries may consume credentials and return a
                # non-secret domain value. All other calls propagate taint from
                # their arguments, so wrappers such as str(secret) stay tainted.
                function_names = _names(value.func)
                call_name = _call_name(value)
                if call_name in SAFE_CREDENTIAL_CONSUMER_CALLS:
                    is_sensitive = False
                else:
                    argument_names = set().union(*(_names(argument) for argument in value.args))
                    argument_names.update(
                        name for keyword in value.keywords for name in _names(keyword.value)
                    )
                    is_sensitive = (
                        not argument_names.isdisjoint(tainted)
                        or any(
                            fragment in name.casefold()
                            for name in function_names
                            for fragment in SENSITIVE_NAME_FRAGMENTS
                        )
                    )
            else:
                is_sensitive = not referenced.isdisjoint(tainted) or any(
                    any(fragment in name.casefold() for fragment in SENSITIVE_NAME_FRAGMENTS)
                    for name in referenced
                )
            if not is_sensitive:
                continue
            new_names = targets - tainted
            if new_names:
                tainted.update(new_names)
                changed = True
    return tainted


def _assert_export_keys_safe(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).casefold()
            assert not any(fragment in lowered for fragment in BLOCKED_EXPORT_KEY_FRAGMENTS)
            _assert_export_keys_safe(item)
    elif isinstance(value, list):
        for item in value:
            _assert_export_keys_safe(item)


def test_application_source_has_no_operational_dotenv_or_database_reference() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in _application_sources())
    normalized = combined.replace("\\", "/").casefold()

    assert "dotenv" not in normalized
    assert "lifecycle.db" not in normalized
    assert ".env" not in normalized


def test_admin_authentication_is_boolean_only_and_secrets_never_reach_display_calls() -> None:
    secrets = {"ADMIN_USERNAME": "demo-admin", "ADMIN_PASSWORD": "demo-password"}

    assert authenticate_admin("demo-admin", "demo-password", secrets) is True
    assert authenticate_admin("demo-admin", "wrong", secrets) is False
    assert type(authenticate_admin(object(), object(), secrets)) is bool

    for path in _application_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tainted_names = _sensitive_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in STREAMLIT_UI_METHODS:
                continue
            displayed_names = set().union(*(_names(argument) for argument in node.args))
            displayed_names.update(
                name
                for keyword in node.keywords
                if keyword.arg != "key"
                for name in _names(keyword.value)
            )
            sensitive_names = displayed_names & tainted_names
            assert not sensitive_names, (
                f"secret passed to Streamlit UI call in {path}: {sorted(sensitive_names)}"
            )


def test_approved_lifecycle_export_recursively_removes_sensitive_and_temporary_fields() -> None:
    state: dict[str, object] = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    equipment_id = add_equipment(
        state,
        project_id,
        {
            "name": "approved-demo",
            "status": "approved",
            "password": "must-not-leak",
            "role": "admin",
            "temporary_path": "/tmp/private-upload.pdf",
            "report": {
                "score": 88,
                "provider_secret": "must-not-leak",
                "details": {
                    "api_key": "must-not-leak",
                    "session_token": "must-not-leak",
                    "source_path": "/tmp/private-source.pdf",
                },
            },
        },
    )

    rows = json.loads(export_approved_equipment(state).decode("utf-8"))
    exported = next(row for row in rows if row["id"] == equipment_id)

    _assert_export_keys_safe(rows)
    assert exported["report"] == {"score": 88, "details": {}}
    assert "/tmp/" not in json.dumps(rows, ensure_ascii=False)


def test_session_reset_removes_only_its_upload_directory_and_clears_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "current-session"
    sibling = tmp_path / "other-session"
    target.mkdir()
    sibling.mkdir()
    stale = tmp_path / "stale-session"
    stale.mkdir()
    import os

    os.utime(stale, (1, 1))
    os.utime(sibling, (1, 1))
    (target / "remove.pdf").write_bytes(b"demo")
    (sibling / "keep.pdf").write_bytes(b"keep")
    monkeypatch.setattr(upload_runtime, "_active_session_tokens", set())
    upload_runtime.register_active_session_token("other-session")
    state: dict[str, object] = {
        "role": "admin",
        "projects": {"private": {"name": "session project"}},
        "_general_selected_project": "private",
        "_general_upload_session_token": "current-session",
        "_ai_action_count": 3,
    }

    reset_session(state, storage_root=tmp_path)

    assert state == {}
    assert not target.exists()
    assert (sibling / "keep.pdf").read_bytes() == b"keep"
    assert not stale.exists()


def test_process_start_cleanup_runs_once_and_removes_prior_session_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = tmp_path / "prior-session"
    active = tmp_path / "active-session"
    prior.mkdir()
    active.mkdir()
    (prior / "source.pdf").write_bytes(b"source")
    (active / "source.pdf").write_bytes(b"active")
    os.utime(prior, (1, 1))
    os.utime(active, (1, 1))
    monkeypatch.setattr(upload_runtime, "_startup_cleanup_done", False)
    monkeypatch.setattr(upload_runtime, "_active_session_tokens", set())
    upload_runtime.register_active_session_token("active-session")

    reloaded = importlib.reload(streamlit_app)

    assert reloaded.cleanup_uploads_on_process_start(storage_root=tmp_path) is True
    assert not prior.exists()
    assert (active / "source.pdf").read_bytes() == b"active"

    current = tmp_path / "current-session"
    current.mkdir()
    reloaded = importlib.reload(streamlit_app)
    assert reloaded.cleanup_uploads_on_process_start(storage_root=tmp_path) is False
    assert current.exists()
    assert (active / "source.pdf").read_bytes() == b"active"


@pytest.mark.parametrize("token", ("bad token", "session/name"))
def test_session_reset_refuses_unsafe_token_and_preserves_state_and_files(
    tmp_path: Path, token: str,
) -> None:
    keep = tmp_path / "keep.pdf"
    keep.write_bytes(b"keep")
    state: dict[str, object] = {
        "role": "guest",
        "projects": {"private": {}},
        "_general_upload_session_token": token,
    }
    before = dict(state)

    with pytest.raises(ValueError):
        reset_session(state, storage_root=tmp_path)

    assert state == before
    assert keep.read_bytes() == b"keep"


def test_session_reset_refuses_traversal_and_absolute_targets_without_deleting_them(
    tmp_path: Path,
) -> None:
    targets = (
        (f"../{tmp_path.name}-traversal-victim", tmp_path.parent / f"{tmp_path.name}-traversal-victim"),
        (str(tmp_path.parent / f"{tmp_path.name}-absolute-victim"), tmp_path.parent / f"{tmp_path.name}-absolute-victim"),
    )
    for token, target in targets:
        target.mkdir()
        keep = target / "keep.pdf"
        keep.write_bytes(b"keep")
        state: dict[str, object] = {
            "role": "admin",
            "projects": {"private": {}},
            "_general_upload_session_token": token,
        }
        before = dict(state)

        with pytest.raises(ValueError):
            reset_session(state, storage_root=tmp_path)

        assert state == before
        assert keep.read_bytes() == b"keep"


def test_session_reset_refuses_symlink_and_preserves_victim_and_state(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    keep = victim / "keep.pdf"
    keep.write_bytes(b"keep")
    (tmp_path / "linked-session").symlink_to(victim, target_is_directory=True)
    state: dict[str, object] = {
        "role": "admin",
        "projects": {"private": {}},
        "_general_upload_session_token": "linked-session",
    }
    before = dict(state)

    with pytest.raises(ValueError, match="symlink"):
        reset_session(state, storage_root=tmp_path)

    assert state == before
    assert keep.read_bytes() == b"keep"
