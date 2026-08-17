import json

from session_store import (
    add_document_metadata,
    add_equipment,
    append_activity_log,
    append_login_log,
    approve_user,
    create_project,
    create_report_version,
    delete_equipment,
    delete_project,
    decide_review,
    export_state,
    initialize_state,
    reject_user,
    remove_document_metadata,
    transition_project,
    update_equipment,
    update_project,
)


def test_project_status_change_is_visible_only_in_current_state() -> None:
    first, second = {}, {}
    initialize_state(first)
    initialize_state(second)

    project_id = create_project(first, {"investment_code": "DEMO-1", "project_name": "테스트"})
    transition_project(first, project_id, "confirmed")

    assert first["projects"][project_id]["status"] == "confirmed"
    assert all(row["status"] != "confirmed" for row in second["projects"].values())


def test_re_review_creates_immutable_report_snapshot() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))

    version_id = create_report_version(state, project_id, "조건 변경")
    state["projects"][project_id]["project_name"] = "변경된 프로젝트"

    version = state["report_versions"][version_id]
    assert version["project_id"] == project_id
    assert version["reason"] == "조건 변경"
    assert version["project_content"]["project_name"] != "변경된 프로젝트"


def test_transition_rejects_invalid_project_status() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))

    try:
        transition_project(state, project_id, "archived")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid project status must raise ValueError")


def test_two_initialized_states_do_not_share_nested_mutables() -> None:
    first, second = {}, {}
    initialize_state(first)
    initialize_state(second)
    first_project_id = next(iter(first["projects"]))
    second_project_id = next(iter(second["projects"]))

    first["projects"][first_project_id]["metadata"]["priority"] = "changed"

    assert second["projects"][second_project_id]["metadata"]["priority"] == "high"


def test_review_decision_updates_review_and_appends_activity() -> None:
    state = {}
    initialize_state(state)
    review_id = next(
        row_id for row_id, row in state["lifecycle_reviews"].items() if row["status"] == "pending"
    )
    before = len(state["activity_logs"])

    decide_review(state, review_id, "approved")

    assert state["lifecycle_reviews"][review_id]["status"] == "approved"
    assert state["lifecycle_reviews"][review_id]["decision"] == "approved"
    assert state["activity_logs"][-1]["action"] == "decide_review"
    assert len(state["activity_logs"]) == before + 1


def test_user_approval_appends_activity() -> None:
    state = {}
    initialize_state(state)
    user_id = next(row_id for row_id, row in state["users"].items() if row["status"] == "pending")

    approve_user(state, user_id)

    assert state["users"][user_id]["status"] == "approved"
    assert state["activity_logs"][-1]["action"] == "approve_user"


def test_create_project_rejects_non_json_payload_values() -> None:
    state = {}
    initialize_state(state)

    try:
        create_project(state, {"project_name": "invalid", "metadata": {"value": object()}})
    except ValueError as error:
        assert str(error) == "Session store values must be JSON serializable."
    else:
        raise AssertionError("non-JSON payload values must raise ValueError")


def test_exported_state_is_json_serializable() -> None:
    state = {}
    initialize_state(state)

    exported = export_state(state)

    assert json.loads(json.dumps(exported, ensure_ascii=False))["projects"] == exported["projects"]


def test_deleting_project_removes_its_report_versions() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    version_id = create_report_version(state, project_id, "project deletion")

    delete_project(state, project_id)

    assert version_id not in state["report_versions"]


def test_activity_log_rejects_non_json_action_or_actor_and_export_remains_safe() -> None:
    state = {}
    initialize_state(state)

    for kwargs in ({"action": object()}, {"action": "event", "actor": object()}):
        try:
            append_activity_log(state, **kwargs)
        except ValueError as error:
            assert str(error) == "Session store values must be JSON serializable."
        else:
            raise AssertionError("non-JSON activity fields must raise ValueError")

    assert json.loads(json.dumps(export_state(state), ensure_ascii=False))["activity_logs"] == state["activity_logs"]


def test_report_version_rejects_non_json_reason_without_mutating_state() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    before = export_state(state)

    try:
        create_report_version(state, project_id, object())
    except ValueError as error:
        assert str(error) == "Session store values must be JSON serializable."
    else:
        raise AssertionError("non-JSON report reasons must raise ValueError")

    assert export_state(state) == before
    assert state["report_versions"] == {}
    json.dumps(export_state(state), ensure_ascii=False)


def test_login_log_rejects_non_json_fields_without_mutating_state() -> None:
    state = {}
    initialize_state(state)
    before = export_state(state)

    for user_id, outcome in ((object(), "success"), ("user-id", object())):
        try:
            append_login_log(state, user_id, outcome)
        except ValueError as error:
            assert str(error) == "Session store values must be JSON serializable."
        else:
            raise AssertionError("non-JSON login fields must raise ValueError")

        assert export_state(state) == before
        json.dumps(export_state(state), ensure_ascii=False)


def test_every_public_mutator_rejects_non_json_input_atomically() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    equipment_id = next(iter(state["equipment"][project_id]))
    document_id = next(iter(state["documents"][project_id]))
    review_id = next(iter(state["lifecycle_reviews"]))
    bad = object()
    mutations = (
        lambda: append_activity_log(state, "event", {"bad": bad}),
        lambda: create_project(state, {"bad": bad}),
        lambda: update_project(state, project_id, {"bad": bad}),
        lambda: transition_project(state, project_id, bad),
        lambda: delete_project(state, bad),
        lambda: add_equipment(state, project_id, {"bad": bad}),
        lambda: update_equipment(state, project_id, equipment_id, {"bad": bad}),
        lambda: delete_equipment(state, project_id, bad),
        lambda: add_document_metadata(state, project_id, {"bad": bad}),
        lambda: remove_document_metadata(state, project_id, bad),
        lambda: create_report_version(state, project_id, bad),
        lambda: approve_user(state, bad),
        lambda: reject_user(state, bad),
        lambda: decide_review(state, review_id, bad),
        lambda: append_login_log(state, bad),
    )

    for mutate in mutations:
        before = export_state(state)

        try:
            mutate()
        except ValueError as error:
            assert str(error) == "Session store values must be JSON serializable."
        else:
            raise AssertionError("non-JSON mutation input must raise ValueError")

        assert export_state(state) == before
        json.dumps(export_state(state), ensure_ascii=False)


def test_update_payload_keys_are_normalized_before_state_mutation() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    equipment_id = next(iter(state["equipment"][project_id]))

    update_project(state, project_id, {1: "project value", "z": "last"})
    update_equipment(state, project_id, equipment_id, {2: "equipment value", "z": "last"})

    assert state["projects"][project_id]["1"] == "project value"
    assert state["equipment"][project_id][equipment_id]["2"] == "equipment value"
    json.dumps(export_state(state), ensure_ascii=False)


def test_mutation_boundary_rejects_non_standard_json_and_non_mapping_payloads() -> None:
    state = {}
    initialize_state(state)
    before = export_state(state)

    for mutate in (
        lambda: create_project(state, {"metadata": {"score": float("nan")}}),
        lambda: append_activity_log(state, "event", []),
    ):
        try:
            mutate()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid JSON boundary input must raise ValueError")

        assert export_state(state) == before
        json.dumps(export_state(state), ensure_ascii=False, allow_nan=False)
