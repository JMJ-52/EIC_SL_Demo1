from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

import ai_demo
from ai_demo import (
    AIActionLimitError,
    AIConfigurationError,
    AIServiceError,
    analyze_project,
    answer_equipment_chat,
    re_review_project,
)
from views.general import _show_analysis_outcome
from lifecycle.extraction.models import IdentifiedEquipment, ParsedUnit
from session_store import (
    add_equipment,
    append_chat_message,
    create_project,
    get_report_version,
    initialize_state,
    list_chat_messages,
    list_equipment,
    list_report_versions,
)
from storage import save_uploads


class Upload:
    name = "inspection.xlsx"

    def getbuffer(self):
        return BytesIO(b"not parsed by injected fake").getbuffer()


@dataclass
class FakeExtraction:
    equipment: list[IdentifiedEquipment]

    def identify_equipment(self, units):
        assert units
        return self.equipment


class FakeFactors:
    def extract_factors(self, criteria, equipment, units):
        return {
            "importance": {"value": "quality_critical", "source_doc": "inspection.xlsx"},
            "unknown": {"value": "must be removed"},
        }


class FakeOpinion:
    def generate_opinion(self, equipment, scoring_result, reference_text, remarks=None, review_reason=None):
        return f"교체 검토 의견{f' ({review_reason})' if review_reason else ''}"


class FakeRisk:
    def generate_checklist(
        self, equipment, scoring_result, reference_text, factor_inputs=None,
        new_model_review=None, remarks=None, review_reason=None,
    ):
        return ["예비품 확보 여부 확인"]


class FakeNewModel:
    def review(self, equipment, new_supplier, new_model_name):
        return {"summary": "신규 모델 확인", "sources": [{"title": "공식", "url": "https://example.test"}]}


class FakeChat:
    def answer(self, project_context, history, question):
        assert question not in [turn["content"] for turn in history]
        return {
            "answer": f"답변: {question}",
            "sources": [
                {"title": "차단", "url": "javascript:alert(1)"},
                {"title": "공식 자료", "url": "https://example.test/source"},
            ],
        }


@pytest.fixture
def fake_state(tmp_path, monkeypatch):
    state = {}
    initialize_state(state)
    project_id = create_project(state, {"investment_code": "P-1", "project_name": "AI 테스트"})
    upload = save_uploads([Upload()], "ai-test-session", tmp_path)
    from session_store import add_document_metadata

    add_document_metadata(state, project_id, upload[0].document_metadata())
    state["_general_upload_session_token"] = "ai-test-session"
    monkeypatch.setattr(ai_demo, "session_storage_root", lambda: tmp_path)
    return state, project_id


@pytest.fixture
def fake_clients():
    equipment = IdentifiedEquipment(
        equipment_type="Motor",
        equipment_label="1호기 모터",
        manufacturer="Demo",
        model_name="M-1",
        new_supplier="Demo Next",
        new_model_name="M-2",
    )
    return SimpleNamespace(
        parse_uploaded_files=lambda paths: [
            ParsedUnit(source_doc="inspection.xlsx", unit_label="Sheet1", text="raw document text")
        ],
        extraction_client=FakeExtraction([equipment]),
        factor_client=FakeFactors(),
        opinion_client=FakeOpinion(),
        risk_checklist_client=FakeRisk(),
        new_model_review_client=FakeNewModel(),
        chatbot_client=FakeChat(),
    )


def test_analysis_persists_json_safe_equipment_report_and_version(fake_state, fake_clients) -> None:
    state, project_id = fake_state

    outcome = analyze_project(state, project_id, clients=fake_clients)

    assert outcome.failed == []
    equipment = list_equipment(state, project_id)
    assert len(equipment) == 1
    assert equipment[0]["technical_opinion"] == "교체 검토 의견"
    assert "unknown" not in equipment[0]["factor_inputs"]
    assert "raw document text" not in str(state)
    assert len(list_report_versions(state, project_id)) == 1
    json.dumps(state, ensure_ascii=False, allow_nan=False)


def test_chat_history_is_isolated_per_equipment(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    equipment_a = add_equipment(state, project_id, {"name": "A", "equipment_type": "Motor"})
    equipment_b = add_equipment(state, project_id, {"name": "B", "equipment_type": "Motor"})

    outcome = answer_equipment_chat(state, project_id, equipment_a, "질문", clients=fake_clients)

    assert outcome.answer == "답변: 질문"
    assert outcome.sources == [{"title": "공식 자료", "url": "https://example.test/source"}]
    assert [turn["role"] for turn in list_chat_messages(state, project_id, equipment_a)] == ["user", "assistant"]
    assert list_chat_messages(state, project_id, equipment_b) == []


def test_missing_openai_key_is_rejected_without_state_mutation(fake_state) -> None:
    state, project_id = fake_state
    before = json.loads(json.dumps(state, ensure_ascii=False))

    with pytest.raises(AIConfigurationError, match="AI 기능을 사용할 수 없습니다"):
        analyze_project(state, project_id, api_key="  ")

    assert state.get("_ai_action_count", 0) == 0
    assert json.loads(json.dumps(state, ensure_ascii=False)) == before


def test_re_review_snapshots_previous_report_before_recalculation(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    analyze_project(state, project_id, clients=fake_clients)
    previous_opinion = list_equipment(state, project_id)[0]["technical_opinion"]

    outcome = re_review_project(state, project_id, "조건 변경", clients=fake_clients)

    version = get_report_version(state, outcome.report_version_id)
    assert version["reason"] == "조건 변경"
    assert next(iter(version["project_content"]["equipment"].values()))["technical_opinion"] == previous_opinion
    assert list_equipment(state, project_id)[0]["technical_opinion"] == "교체 검토 의견 (조건 변경)"


def test_ai_action_limit_is_shared_by_analysis_re_review_and_chat(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    analyze_project(state, project_id, clients=fake_clients)
    equipment_id = list_equipment(state, project_id)[0]["id"]
    answer_equipment_chat(state, project_id, equipment_id, "q1", clients=fake_clients)
    answer_equipment_chat(state, project_id, equipment_id, "q2", clients=fake_clients)
    re_review_project(state, project_id, "r1", clients=fake_clients)
    answer_equipment_chat(state, project_id, equipment_id, "q3", clients=fake_clients)

    before = list_chat_messages(state, project_id, equipment_id)
    with pytest.raises(AIActionLimitError, match="사용 한도"):
        answer_equipment_chat(state, project_id, equipment_id, "blocked", clients=fake_clients)
    assert list_chat_messages(state, project_id, equipment_id) == before


def test_empty_identification_does_not_delete_manual_equipment(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    manual_id = add_equipment(state, project_id, {"name": "수동 설비", "equipment_type": "Motor"})
    fake_clients.extraction_client = FakeExtraction([])

    with pytest.raises(AIServiceError, match="처리하지 못했습니다"):
        analyze_project(state, project_id, clients=fake_clients)

    assert {row["id"] for row in list_equipment(state, project_id)} == {manual_id}


def test_partial_failure_preserves_manual_and_prior_analyzed_rows(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    analyze_project(state, project_id, clients=fake_clients)
    prior_id = list_equipment(state, project_id)[0]["id"]
    append_chat_message(state, project_id, prior_id, "user", "보존할 대화")
    manual_id = add_equipment(state, project_id, {"name": "수동 설비", "equipment_type": "Motor"})
    fake_clients.extraction_client = FakeExtraction([
        IdentifiedEquipment("Motor", "2호기 모터", "Demo", "M-2"),
        IdentifiedEquipment("Unknown", "판정 실패 설비", None, None),
    ])

    outcome = analyze_project(state, project_id, clients=fake_clients)

    equipment_ids = {row["id"] for row in list_equipment(state, project_id)}
    assert {prior_id, manual_id}.issubset(equipment_ids)
    assert list_chat_messages(state, project_id, prior_id)[0]["content"] == "보존할 대화"
    assert len(outcome.failed) == 1


def test_provider_citations_are_limited_to_parsed_document_names(fake_state, fake_clients) -> None:
    state, project_id = fake_state

    class MaliciousFactors:
        def extract_factors(self, criteria, equipment, units):
            return {
                "importance": {
                    "value": "quality_critical",
                    "source_doc": "raw uploaded paragraph that is not a filename",
                    "source_page": "short raw sentence from the uploaded document",
                }
            }

    fake_clients.factor_client = MaliciousFactors()
    analyze_project(state, project_id, clients=fake_clients)

    factors = list_equipment(state, project_id)[0]["factor_inputs"]["importance"]
    assert "source_doc" not in factors
    assert "source_page" not in factors
    assert "raw uploaded paragraph" not in str(state)


def test_provider_failure_message_is_redacted(fake_state, fake_clients) -> None:
    state, project_id = fake_state

    class BrokenExtraction:
        def identify_equipment(self, units):
            raise RuntimeError("provider secret sk-sensitive and raw document")

    fake_clients.extraction_client = BrokenExtraction()
    with pytest.raises(AIServiceError) as caught:
        analyze_project(state, project_id, clients=fake_clients)

    assert "sk-sensitive" not in str(caught.value)
    assert "raw document" not in str(caught.value)
    assert "sk-sensitive" not in str(state)


def test_no_tavily_new_model_review_persists_explicit_limitation(fake_state, fake_clients) -> None:
    state, project_id = fake_state
    fake_clients.new_model_web_available = False

    analyze_project(state, project_id, clients=fake_clients)

    review = list_equipment(state, project_id)[0]["new_model_review"]
    assert review["summary"] == "신규 모델 확인"
    assert review["web_research_available"] is False
    assert "웹 검색을 사용할 수 없어" in review["limitation"]


def test_real_client_bundle_constructs_new_model_review_without_tavily(monkeypatch) -> None:
    captured = {}

    class FakeNewModelClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(ai_demo, "NewModelReviewClient", FakeNewModelClient)
    bundle = ai_demo._real_clients("not-a-real-key", None, None)

    assert bundle.new_model_review_client is not None
    assert callable(captured["search_fn"])
    assert captured["search_fn"](None, "query") == []


def test_ai_rejects_document_path_owned_by_another_upload_session(
    fake_state, fake_clients, tmp_path, monkeypatch,
) -> None:
    state, _ = fake_state
    project_id = create_project(state, {"project_name": "cross session"})
    upload = save_uploads([Upload()], "other-session", tmp_path)
    from session_store import add_document_metadata

    add_document_metadata(state, project_id, upload[0].document_metadata())
    state["_general_upload_session_token"] = "current-session"
    monkeypatch.setattr(ai_demo, "session_storage_root", lambda: tmp_path)

    with pytest.raises(ai_demo.AIInputError, match="업로드 문서"):
        analyze_project(state, project_id, clients=fake_clients)


def test_detail_failure_is_structured_persisted_and_not_displayed_as_success(
    fake_state, fake_clients,
) -> None:
    state, project_id = fake_state

    class BrokenRisk:
        def generate_checklist(self, *args, **kwargs):
            raise RuntimeError("provider detail")

    fake_clients.risk_checklist_client = BrokenRisk()
    outcome = analyze_project(state, project_id, clients=fake_clients)
    row = list_equipment(state, project_id)[0]

    assert outcome.warnings == ["1호기 모터: 리스크 체크리스트를 완료하지 못했습니다."]
    assert row["risk_checklist"] == []
    assert row["risk_checklist_status"] == "failed"

    class FakeStreamlit:
        warnings: list[str] = []
        successes: list[str] = []
        captions: list[str] = []

        def warning(self, value): self.warnings.append(value)
        def success(self, value): self.successes.append(value)
        def caption(self, value): self.captions.append(value)

    st = FakeStreamlit()
    _show_analysis_outcome(st, outcome)
    assert st.warnings and not st.successes
    assert "세부 실패 1건" in st.warnings[0]
