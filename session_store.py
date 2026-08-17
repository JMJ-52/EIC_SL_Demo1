"""A Streamlit-independent boundary for all session-only demo mutations."""

from __future__ import annotations

import json
from collections.abc import Mapping, MutableMapping
from typing import Any, cast
from uuid import uuid4

from demo_data import make_demo_state, utc_timestamp
from models import PROJECT_STATUSES, USER_STATUSES


_JSON_ERROR = "Session store values must be JSON serializable."
_APPROVED_EQUIPMENT_STATUS = "approved"


def _new_id() -> str:
    return str(uuid4())


def _json_copy(value: object) -> Any:
    """Validate JSON compatibility while returning an independent plain value."""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(_JSON_ERROR) from error


def _json_mapping(value: object) -> dict[str, Any]:
    """Normalize a mapping, including its keys, through the JSON boundary."""

    if not isinstance(value, Mapping):
        raise ValueError("Session store mapping values must be JSON objects.")
    try:
        plain_value = dict(value)
    except (TypeError, ValueError) as error:
        raise ValueError(_JSON_ERROR) from error
    normalized = _json_copy(plain_value)
    if not isinstance(normalized, dict):
        raise ValueError("Session store mapping values must be JSON objects.")
    return cast(dict[str, Any], normalized)


def _json_string(value: object) -> str:
    """Normalize and type-check a public string argument."""

    normalized = _json_copy(value)
    if not isinstance(normalized, str):
        raise ValueError("Session store string values must be strings.")
    return normalized


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Session store collection '{name}' is unavailable.")
    return cast(dict[str, Any], value)


def _project(state: MutableMapping[str, object], project_id: str) -> dict[str, Any]:
    projects = _mapping(state.get("projects"), "projects")
    try:
        return _mapping(projects[project_id], "project")
    except KeyError as error:
        raise KeyError(f"Unknown project: {project_id}") from error


def _activity(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    value = state.get("activity_logs")
    if not isinstance(value, list):
        raise RuntimeError("Session store collection 'activity_logs' is unavailable.")
    return cast(list[dict[str, Any]], value)


def _prepare_activity(
    state: MutableMapping[str, object], action: object,
    details: object = None, actor: object = "system",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate an activity record and its destination without mutating state."""

    record = {
        "id": _new_id(),
        "action": _json_string(action),
        "timestamp": utc_timestamp(),
        "actor": _json_string(actor),
        "details": _json_mapping({} if details is None else details),
    }
    return _activity(state), record


def initialize_state(state: MutableMapping[str, object]) -> None:
    """Initialize a mapping once with an independent copy of demo data."""

    if state.get("_session_store_initialized") is True:
        return
    state.update(_json_mapping(make_demo_state()))


def list_projects(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    """Return independent JSON-safe project rows for presentation code."""

    projects = _mapping(state.get("projects"), "projects")
    return cast(list[dict[str, Any]], _json_copy(list(projects.values())))


def list_users(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    """Return independent user rows for administrator presentation code."""

    users = _mapping(state.get("users"), "users")
    return cast(list[dict[str, Any]], _json_copy(list(users.values())))


def list_lifecycle_reviews(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    """Return independent lifecycle-review rows for administrator presentation code."""

    reviews = _mapping(state.get("lifecycle_reviews"), "lifecycle_reviews")
    return cast(list[dict[str, Any]], _json_copy(list(reviews.values())))


def list_login_logs(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    """Return independent login-log rows for administrator presentation code."""

    logs = state.get("login_logs")
    if not isinstance(logs, list):
        raise RuntimeError("Session store collection 'login_logs' is unavailable.")
    return cast(list[dict[str, Any]], _json_copy(logs))


def list_activity_logs(state: MutableMapping[str, object]) -> list[dict[str, Any]]:
    """Return independent activity-log rows for administrator presentation code."""

    return cast(list[dict[str, Any]], _json_copy(_activity(state)))


def get_statistics(state: MutableMapping[str, object]) -> dict[str, Any]:
    """Return an independent statistics snapshot for administrator metrics."""

    return cast(dict[str, Any], _json_copy(_mapping(state.get("statistics"), "statistics")))


def get_project(state: MutableMapping[str, object], project_id: str) -> dict[str, Any]:
    """Return one independent JSON-safe project record."""

    return cast(dict[str, Any], _json_copy(_project(state, _json_string(project_id))))


def list_equipment(state: MutableMapping[str, object], project_id: str) -> list[dict[str, Any]]:
    """Return independent equipment rows associated with one project."""

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    rows = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    return cast(list[dict[str, Any]], _json_copy(list(rows.values())))


def list_documents(state: MutableMapping[str, object], project_id: str) -> list[dict[str, Any]]:
    """Return independent document metadata rows for one project."""

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    rows = _mapping(
        _mapping(state.get("documents"), "documents").get(safe_project_id), "project documents",
    )
    return cast(list[dict[str, Any]], _json_copy(list(rows.values())))


def get_report_data(state: MutableMapping[str, object], project_id: str) -> dict[str, Any]:
    """Return an independent report summary for one project."""

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    report_data = _mapping(state.get("report_data"), "report_data")
    return cast(dict[str, Any], _json_copy(_mapping(report_data.get(safe_project_id, {}), "report data")))


def set_report_data(
    state: MutableMapping[str, object], project_id: str, payload: Mapping[str, object],
) -> None:
    """Replace a project's generated report through the JSON-safe store boundary."""

    safe_project_id = _json_string(project_id)
    safe_payload = _json_mapping(payload)
    _project(state, safe_project_id)
    reports = _mapping(state.get("report_data"), "report_data")
    activity, activity_record = _prepare_activity(
        state, "set_report_data", {"project_id": safe_project_id},
    )
    reports[safe_project_id] = safe_payload
    activity.append(activity_record)


def list_report_versions(state: MutableMapping[str, object], project_id: str) -> list[dict[str, Any]]:
    """Return independent report-version metadata for one project."""

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    versions = _mapping(state.get("report_versions"), "report_versions")
    rows = [row for row in versions.values() if _mapping(row, "report version").get("project_id") == safe_project_id]
    return cast(list[dict[str, Any]], _json_copy(rows))


def get_report_version(state: MutableMapping[str, object], report_version_id: str) -> dict[str, Any]:
    """Return one independent immutable report-version snapshot."""

    safe_version_id = _json_string(report_version_id)
    versions = _mapping(state.get("report_versions"), "report_versions")
    try:
        version = _mapping(versions[safe_version_id], "report version")
    except KeyError as error:
        raise KeyError(f"Unknown report version: {safe_version_id}") from error
    return cast(dict[str, Any], _json_copy(version))


def append_activity_log(
    state: MutableMapping[str, object], action: str, details: Mapping[str, object] | None = None,
    actor: str = "system",
) -> str:
    """Append an audit record and return its UUID string."""

    activity, record = _prepare_activity(state, action, details, actor)
    activity.append(record)
    return cast(str, record["id"])


def create_project(state: MutableMapping[str, object], payload: Mapping[str, object]) -> str:
    """Create a project from JSON-compatible form data."""

    safe_payload = _json_mapping(payload)
    project_id = _new_id()
    timestamp = utc_timestamp()
    status = str(safe_payload.get("status", "draft"))
    if status not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status: {status}")
    reserved = {"id", "created_at", "updated_at", "status"}
    project = {
        "id": project_id,
        "investment_code": str(safe_payload.get("investment_code", "")),
        "project_name": str(safe_payload.get("project_name", "")),
        "status": status,
        "description": str(safe_payload.get("description", "")),
        "created_at": timestamp,
        "updated_at": timestamp,
        "owner": str(safe_payload.get("owner", "")),
        "metadata": _json_mapping(safe_payload.get("metadata", {})),
    }
    project.update({key: value for key, value in safe_payload.items() if key not in reserved and key not in project})
    projects = _mapping(state.get("projects"), "projects")
    equipment = _mapping(state.get("equipment"), "equipment")
    documents = _mapping(state.get("documents"), "documents")
    report_data = _mapping(state.get("report_data"), "report_data")
    activity, activity_record = _prepare_activity(state, "create_project", {"project_id": project_id})
    projects[project_id] = project
    equipment[project_id] = {}
    documents[project_id] = {}
    report_data[project_id] = {}
    activity.append(activity_record)
    return project_id


def update_project(state: MutableMapping[str, object], project_id: str, payload: Mapping[str, object]) -> None:
    """Update project fields while preserving its identity and creation time."""

    safe_project_id = _json_string(project_id)
    safe_payload = _json_mapping(payload)
    project = _project(state, safe_project_id)
    changes = {key: value for key, value in safe_payload.items() if key not in {"id", "created_at"}}
    if "status" in changes and str(changes["status"]) not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status: {changes['status']}")
    activity, activity_record = _prepare_activity(
        state, "update_project", {"project_id": safe_project_id, "fields": sorted(changes)},
    )
    project.update(changes)
    project["updated_at"] = utc_timestamp()
    activity.append(activity_record)


def transition_project(state: MutableMapping[str, object], project_id: str, status: str) -> None:
    """Set a project lifecycle status from the closed set of valid states."""

    safe_project_id = _json_string(project_id)
    safe_status = _json_string(status)
    if safe_status not in PROJECT_STATUSES:
        raise ValueError(f"Invalid project status: {safe_status}")
    project = _project(state, safe_project_id)
    previous = _json_copy(project["status"])
    activity, activity_record = _prepare_activity(
        state, "transition_project", {"project_id": safe_project_id, "from": previous, "to": safe_status},
    )
    project["status"] = safe_status
    project["updated_at"] = utc_timestamp()
    activity.append(activity_record)


def delete_project(state: MutableMapping[str, object], project_id: str) -> None:
    """Remove one project and every session collection scoped to it."""

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    collections = {
        name: _mapping(state.get(name), name)
        for name in ("projects", "equipment", "documents", "report_data")
    }
    report_versions = _mapping(state.get("report_versions"), "report_versions")
    version_ids = [
        version_id for version_id, version in report_versions.items()
        if _mapping(version, "report version").get("project_id") == safe_project_id
    ]
    activity, activity_record = _prepare_activity(state, "delete_project", {"project_id": safe_project_id})
    for collection in collections.values():
        collection.pop(safe_project_id, None)
    for version_id in version_ids:
        report_versions.pop(version_id)
    chat_messages = _mapping(state.get("chat_messages"), "chat_messages")
    chat_messages.pop(safe_project_id, None)
    activity.append(activity_record)


def add_equipment(state: MutableMapping[str, object], project_id: str, payload: Mapping[str, object]) -> str:
    """Add equipment beneath a project and return its UUID string."""

    safe_project_id = _json_string(project_id)
    safe_payload = _json_mapping(payload)
    _project(state, safe_project_id)
    equipment_id = _new_id()
    record = {
        "id": equipment_id, "project_id": safe_project_id, "name": str(safe_payload.get("name", "")),
        "equipment_type": str(safe_payload.get("equipment_type", "")),
        "manufacturer": str(safe_payload.get("manufacturer", "")),
        "model_name": str(safe_payload.get("model_name", "")),
        "status": str(safe_payload.get("status", "pending")),
        "report": _json_mapping(safe_payload.get("report", {})),
    }
    record.update({
        key: value for key, value in safe_payload.items()
        if key not in {"id", "project_id"} and key not in record
    })
    project_equipment = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    activity, activity_record = _prepare_activity(
        state, "add_equipment", {"project_id": safe_project_id, "equipment_id": equipment_id},
    )
    project_equipment[equipment_id] = record
    activity.append(activity_record)
    return equipment_id


create_equipment = add_equipment


def update_equipment(
    state: MutableMapping[str, object], project_id: str, equipment_id: str, payload: Mapping[str, object],
) -> None:
    """Update equipment fields without allowing an ID or project move."""

    safe_project_id = _json_string(project_id)
    safe_equipment_id = _json_string(equipment_id)
    safe_payload = _json_mapping(payload)
    rows = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    if safe_equipment_id not in rows:
        raise KeyError(f"Unknown equipment: {safe_equipment_id}")
    row = _mapping(rows[safe_equipment_id], "equipment")
    changes = {key: value for key, value in safe_payload.items() if key not in {"id", "project_id"}}
    activity, activity_record = _prepare_activity(
        state, "update_equipment",
        {"project_id": safe_project_id, "equipment_id": safe_equipment_id, "fields": sorted(changes)},
    )
    row.update(changes)
    activity.append(activity_record)


def delete_equipment(state: MutableMapping[str, object], project_id: str, equipment_id: str) -> None:
    """Remove one equipment row from a project."""

    safe_project_id = _json_string(project_id)
    safe_equipment_id = _json_string(equipment_id)
    rows = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    if safe_equipment_id not in rows:
        raise KeyError(f"Unknown equipment: {safe_equipment_id}")
    activity, activity_record = _prepare_activity(
        state, "delete_equipment", {"project_id": safe_project_id, "equipment_id": safe_equipment_id},
    )
    rows.pop(safe_equipment_id)
    project_chats = _mapping(state.get("chat_messages"), "chat_messages").get(safe_project_id)
    if isinstance(project_chats, dict):
        project_chats.pop(safe_equipment_id, None)
    activity.append(activity_record)


def replace_project_equipment(
    state: MutableMapping[str, object], project_id: str, payloads: list[Mapping[str, object]],
    *, preserve_unmanaged: bool = False, preserve_stale: bool = False,
) -> list[str]:
    """Atomically replace analyzed rows, optionally retaining unrelated data.

    ``preserve_unmanaged`` keeps manually entered rows that do not carry the
    ``analysis_managed`` marker. ``preserve_stale`` additionally keeps prior
    analyzed rows when a new batch was only partially successful.
    """

    safe_project_id = _json_string(project_id)
    _project(state, safe_project_id)
    if not isinstance(payloads, list):
        raise ValueError("Session store equipment values must be a list.")
    safe_payloads = [_json_mapping(payload) for payload in payloads]
    existing = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    replacements: dict[str, dict[str, Any]] = {}
    if preserve_unmanaged or preserve_stale:
        replacements.update({
            equipment_id: cast(dict[str, Any], _json_copy(row))
            for equipment_id, row in existing.items()
            if preserve_stale or not _mapping(row, "equipment").get("analysis_managed")
        })
    saved_ids: list[str] = []
    for payload in safe_payloads:
        requested_id = payload.get("id")
        equipment_id = requested_id if isinstance(requested_id, str) and requested_id in existing else _new_id()
        record = {
            "id": equipment_id,
            "project_id": safe_project_id,
            "name": str(payload.get("name", "")),
            "equipment_type": str(payload.get("equipment_type", "")),
            "manufacturer": str(payload.get("manufacturer", "")),
            "model_name": str(payload.get("model_name", "")),
            "status": str(payload.get("status", "reviewed")),
            "report": _json_mapping(payload.get("report", {})),
        }
        record.update({
            key: value for key, value in payload.items()
            if key not in {"id", "project_id"} and key not in record
        })
        replacements[equipment_id] = record
        saved_ids.append(equipment_id)
    activity, activity_record = _prepare_activity(
        state, "replace_project_equipment",
        {
            "project_id": safe_project_id,
            "equipment_ids": list(replacements),
            "preserve_unmanaged": preserve_unmanaged,
            "preserve_stale": preserve_stale,
        },
    )
    equipment = _mapping(state.get("equipment"), "equipment")
    equipment[safe_project_id] = replacements
    project_chats = _mapping(state.get("chat_messages"), "chat_messages").get(safe_project_id)
    if isinstance(project_chats, dict):
        for equipment_id in list(project_chats):
            if equipment_id not in replacements:
                project_chats.pop(equipment_id)
    activity.append(activity_record)
    return saved_ids


def list_chat_messages(
    state: MutableMapping[str, object], project_id: str, equipment_id: str,
) -> list[dict[str, Any]]:
    """Return one independent transcript scoped to a project/equipment pair."""

    safe_project_id = _json_string(project_id)
    safe_equipment_id = _json_string(equipment_id)
    rows = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    if safe_equipment_id not in rows:
        raise KeyError(f"Unknown equipment: {safe_equipment_id}")
    chat_messages = _mapping(state.get("chat_messages"), "chat_messages")
    project_chats = chat_messages.get(safe_project_id, {})
    if not isinstance(project_chats, dict):
        raise RuntimeError("Session store project chat collection is unavailable.")
    transcript = project_chats.get(safe_equipment_id, [])
    if not isinstance(transcript, list):
        raise RuntimeError("Session store equipment chat transcript is unavailable.")
    return cast(list[dict[str, Any]], _json_copy(transcript))


def append_chat_message(
    state: MutableMapping[str, object], project_id: str, equipment_id: str,
    role: str, content: str, sources: list[Mapping[str, object]] | None = None,
) -> None:
    """Append a JSON-safe user or assistant turn to one equipment transcript."""

    safe_project_id = _json_string(project_id)
    safe_equipment_id = _json_string(equipment_id)
    safe_role = _json_string(role)
    safe_content = _json_string(content)
    if safe_role not in {"user", "assistant"}:
        raise ValueError("Chat role must be user or assistant.")
    rows = _mapping(
        _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
    )
    if safe_equipment_id not in rows:
        raise KeyError(f"Unknown equipment: {safe_equipment_id}")
    safe_sources = _json_copy(sources or [])
    if not isinstance(safe_sources, list):
        raise ValueError("Chat sources must be a list.")
    record = {
        "role": safe_role, "content": safe_content,
        "sources": safe_sources, "timestamp": utc_timestamp(),
    }
    chat_messages = _mapping(state.get("chat_messages"), "chat_messages")
    project_chats = chat_messages.setdefault(safe_project_id, {})
    if not isinstance(project_chats, dict):
        raise RuntimeError("Session store project chat collection is unavailable.")
    transcript = project_chats.setdefault(safe_equipment_id, [])
    if not isinstance(transcript, list):
        raise RuntimeError("Session store equipment chat transcript is unavailable.")
    transcript.append(record)


def consume_ai_action(state: MutableMapping[str, object], limit: int) -> int:
    """Reserve one shared AI action, rejecting attempts beyond ``limit``."""

    if not isinstance(limit, int) or limit < 1:
        raise ValueError("AI action limit must be a positive integer.")
    current = state.get("_ai_action_count", 0)
    if not isinstance(current, int) or isinstance(current, bool) or current < 0:
        raise RuntimeError("Session AI action counter is unavailable.")
    if current >= limit:
        raise ValueError("AI action limit reached.")
    state["_ai_action_count"] = current + 1
    return current + 1


def add_document_metadata(state: MutableMapping[str, object], project_id: str, payload: Mapping[str, object]) -> str:
    """Associate JSON-safe upload metadata with a project."""

    safe_project_id = _json_string(project_id)
    safe_payload = _json_mapping(payload)
    _project(state, safe_project_id)
    document_id = _new_id()
    document = {
        "id": document_id, "project_id": safe_project_id,
        "name": str(safe_payload.get("name", "")), "uploaded_at": utc_timestamp(),
    }
    document.update({
        key: value for key, value in safe_payload.items()
        if key not in {"id", "project_id", "uploaded_at"}
    })
    project_documents = _mapping(
        _mapping(state.get("documents"), "documents").get(safe_project_id), "project documents",
    )
    activity, activity_record = _prepare_activity(
        state, "add_document_metadata", {"project_id": safe_project_id, "document_id": document_id},
    )
    project_documents[document_id] = document
    activity.append(activity_record)
    return document_id


def remove_document_metadata(state: MutableMapping[str, object], project_id: str, document_id: str) -> None:
    """Remove one document metadata record from a project."""

    safe_project_id = _json_string(project_id)
    safe_document_id = _json_string(document_id)
    documents = _mapping(
        _mapping(state.get("documents"), "documents").get(safe_project_id), "project documents",
    )
    if safe_document_id not in documents:
        raise KeyError(f"Unknown document: {safe_document_id}")
    activity, activity_record = _prepare_activity(
        state, "remove_document_metadata", {"project_id": safe_project_id, "document_id": safe_document_id},
    )
    documents.pop(safe_document_id)
    activity.append(activity_record)


def create_report_version(state: MutableMapping[str, object], project_id: str, reason: str) -> str:
    """Save an independent deep-copy project snapshot for re-review history."""

    safe_project_id = _json_string(project_id)
    safe_reason = _json_string(reason)
    project_content = _json_copy({
        **_project(state, safe_project_id),
        "equipment": _mapping(
            _mapping(state.get("equipment"), "equipment").get(safe_project_id), "project equipment",
        ),
        "documents": _mapping(
            _mapping(state.get("documents"), "documents").get(safe_project_id), "project documents",
        ),
        "report_data": _mapping(state.get("report_data"), "report_data").get(safe_project_id, {}),
    })
    version_id = _new_id()
    version = {
        "id": version_id, "project_id": safe_project_id,
        "reason": safe_reason, "timestamp": utc_timestamp(),
        "project_content": project_content,
    }
    report_versions = _mapping(state.get("report_versions"), "report_versions")
    activity, activity_record = _prepare_activity(
        state, "create_report_version",
        {"project_id": safe_project_id, "report_version_id": version_id, "reason": safe_reason},
    )
    report_versions[version_id] = version
    activity.append(activity_record)
    return version_id


def approve_user(state: MutableMapping[str, object], user_id: str) -> None:
    """Approve a pending user and record the required audit activity."""

    _set_user_status(state, user_id, "approved", "approve_user")


def reject_user(state: MutableMapping[str, object], user_id: str) -> None:
    """Reject a user and record an audit activity."""

    _set_user_status(state, user_id, "rejected", "reject_user")


def _set_user_status(state: MutableMapping[str, object], user_id: str, status: str, action: str) -> None:
    safe_user_id = _json_string(user_id)
    safe_status = _json_string(status)
    safe_action = _json_string(action)
    if safe_status not in USER_STATUSES:
        raise ValueError(f"Invalid user status: {safe_status}")
    users = _mapping(state.get("users"), "users")
    if safe_user_id not in users:
        raise KeyError(f"Unknown user: {safe_user_id}")
    user = _mapping(users[safe_user_id], "user")
    activity, activity_record = _prepare_activity(
        state, safe_action, {"user_id": safe_user_id, "status": safe_status},
    )
    user["status"] = safe_status
    user["decided_at"] = utc_timestamp()
    activity.append(activity_record)


def decide_review(state: MutableMapping[str, object], review_id: str, decision: str) -> None:
    """Approve or reject a lifecycle review and record an audit activity."""

    safe_review_id = _json_string(review_id)
    safe_decision = _json_string(decision)
    if safe_decision not in {"approved", "rejected"}:
        raise ValueError(f"Invalid review decision: {safe_decision}")
    reviews = _mapping(state.get("lifecycle_reviews"), "lifecycle_reviews")
    if safe_review_id not in reviews:
        raise KeyError(f"Unknown lifecycle review: {safe_review_id}")
    review = _mapping(reviews[safe_review_id], "lifecycle review")
    linked_equipment: dict[str, Any] | None = None
    project_id = review.get("project_id")
    equipment_id = review.get("equipment_id")
    if safe_decision == "approved" and isinstance(project_id, str) and isinstance(equipment_id, str):
        project_rows = _mapping(
            _mapping(state.get("equipment"), "equipment").get(project_id), "project equipment",
        )
        if equipment_id not in project_rows:
            raise KeyError(f"Unknown equipment: {equipment_id}")
        linked_equipment = _mapping(project_rows[equipment_id], "equipment")
    activity, activity_record = _prepare_activity(
        state, "decide_review", {
            "review_id": safe_review_id, "decision": safe_decision,
            "project_id": project_id, "equipment_id": equipment_id,
        },
    )
    review["status"] = safe_decision
    review["decision"] = safe_decision
    review["decided_at"] = utc_timestamp()
    if linked_equipment is not None:
        linked_equipment["status"] = _APPROVED_EQUIPMENT_STATUS
        linked_equipment["approved_review_id"] = safe_review_id
        linked_equipment["approved_at"] = review["decided_at"]
    activity.append(activity_record)


def append_login_log(
    state: MutableMapping[str, object], user_id: str, outcome: str = "success",
) -> str:
    """Append a login event for the current session."""

    safe_user_id = _json_string(user_id)
    safe_outcome = _json_string(outcome)
    log_id = _new_id()
    value = state.get("login_logs")
    if not isinstance(value, list):
        raise RuntimeError("Session store collection 'login_logs' is unavailable.")
    login_logs = cast(list[dict[str, Any]], value)
    record = {
        "id": log_id, "user_id": safe_user_id,
        "timestamp": utc_timestamp(), "outcome": safe_outcome,
    }
    activity, activity_record = _prepare_activity(
        state, "append_login_log", {"user_id": safe_user_id, "outcome": safe_outcome},
    )
    login_logs.append(record)
    activity.append(activity_record)
    return log_id


def export_state(state: MutableMapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe, independent export of all current session data."""

    return cast(dict[str, object], _json_copy(dict(state)))


def _public_equipment_value(value: object) -> Any:
    """Copy report values while removing credentials and server-local paths."""

    blocked_fragments = ("password", "secret", "token", "api_key", "path", "role")
    if isinstance(value, Mapping):
        return {
            str(key): _public_equipment_value(item)
            for key, item in value.items()
            if not any(fragment in str(key).lower() for fragment in blocked_fragments)
        }
    if isinstance(value, list):
        return [_public_equipment_value(item) for item in value]
    return _json_copy(value)


def export_approved_equipment(state: MutableMapping[str, object]) -> bytes:
    """Export approved lifecycle equipment as safe UTF-8 JSON download content.

    The export has an intentionally narrow schema, so arbitrary equipment
    metadata (including passwords, roles, and local upload paths) cannot leak
    into an administrator download.
    """

    public_fields = (
        "id", "project_id", "name", "equipment_type", "manufacturer",
        "model_name", "status", "report",
    )
    equipment = _mapping(state.get("equipment"), "equipment")
    approved_rows: list[dict[str, Any]] = []
    for rows in equipment.values():
        for value in _mapping(rows, "project equipment").values():
            row = _mapping(value, "equipment")
            if row.get("status") != _APPROVED_EQUIPMENT_STATUS:
                continue
            approved_rows.append({
                field: _public_equipment_value(row[field]) for field in public_fields if field in row
            })
    return json.dumps(approved_rows, ensure_ascii=False, allow_nan=False).encode("utf-8")
