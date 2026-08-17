"""Session-only AI orchestration for the private Streamlit demo.

This adapter deliberately composes the existing parsers, criteria, scoring,
and AI clients without importing the SQLite-backed assessment pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, MutableMapping
from urllib.parse import urlparse

from lifecycle.assessment.chat_client import ChatbotClient, build_project_context
from lifecycle.assessment.extraction_client import OpenAIExtractionClient
from lifecycle.assessment.factor_extraction import FactorExtractionClient, _sanitize_factors
from lifecycle.assessment.new_model_review import NewModelReviewClient
from lifecycle.assessment.opinion import TechnicalOpinionClient
from lifecycle.assessment.reference import load_reference_text
from lifecycle.assessment.risk_checklist import RiskChecklistClient
from lifecycle.criteria_loader import load_criteria
from lifecycle.extraction.models import IdentifiedEquipment
from lifecycle.extraction.pipeline import parse_uploaded_files
from lifecycle.scoring import compute_score

from demo_data import utc_timestamp
from session_store import (
    append_chat_message,
    consume_ai_action,
    create_report_version,
    get_project,
    list_chat_messages,
    list_documents,
    list_equipment,
    replace_project_equipment,
    set_report_data,
    transition_project,
)
from storage import session_storage_root, validated_session_file


AI_ACTION_LIMIT = 5
DEFAULT_MODEL = "gpt-4o"
_AI_UNAVAILABLE = "AI 기능을 사용할 수 없습니다."
_AI_FAILED = "AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요."
_AI_LIMIT_REACHED = "이 세션의 AI 사용 한도에 도달했습니다."
_MISSING = object()


class AIConfigurationError(RuntimeError):
    """Raised when a real provider call is requested without configuration."""


class AIActionLimitError(RuntimeError):
    """Raised when the shared session action cap has already been consumed."""


class AIInputError(ValueError):
    """Raised for missing or invalid project inputs without exposing file paths."""


class AIServiceError(RuntimeError):
    """Raised with a sanitized message when a provider or parser fails."""


@dataclass(frozen=True)
class AnalysisOutcome:
    succeeded: list[str]
    failed: list[str]
    report_version_id: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatOutcome:
    answer: str
    sources: list[dict[str, str]]


def _injected_value(clients: object, *names: str, default: object = _MISSING) -> object:
    for name in names:
        if isinstance(clients, Mapping) and name in clients:
            return clients[name]
        if hasattr(clients, name):
            return getattr(clients, name)
    if default is not _MISSING:
        return default
    raise AIServiceError(_AI_FAILED)


def _real_clients(api_key: str, model: str | None, tavily_api_key: str | None) -> SimpleNamespace:
    model_name = model.strip() if isinstance(model, str) and model.strip() else DEFAULT_MODEL
    tavily_key = tavily_api_key.strip() if isinstance(tavily_api_key, str) and tavily_api_key.strip() else None
    return SimpleNamespace(
        parse_uploaded_files=parse_uploaded_files,
        extraction_client=OpenAIExtractionClient(api_key=api_key, model=model_name),
        factor_client=FactorExtractionClient(api_key=api_key, model=model_name),
        opinion_client=TechnicalOpinionClient(api_key=api_key, model=model_name),
        risk_checklist_client=RiskChecklistClient(api_key=api_key, model=model_name),
        new_model_review_client=NewModelReviewClient(
            api_key=api_key, model=model_name, tavily_api_key=tavily_key,
            search_fn=None if tavily_key else (lambda api_key, query, max_results=5: []),
        ),
        new_model_web_available=bool(tavily_key),
        chatbot_client=ChatbotClient(
            api_key=api_key, model=model_name, tavily_api_key=tavily_key,
        ),
    )


def _resolve_clients(
    clients: object | None, api_key: str | None, model: str | None, tavily_api_key: str | None,
) -> object:
    if clients is not None:
        return clients
    if not isinstance(api_key, str) or not api_key.strip():
        raise AIConfigurationError(_AI_UNAVAILABLE)
    return _real_clients(api_key.strip(), model, tavily_api_key)


def _reserve_action(state: MutableMapping[str, object]) -> None:
    try:
        consume_ai_action(state, AI_ACTION_LIMIT)
    except ValueError:
        raise AIActionLimitError(_AI_LIMIT_REACHED) from None


def _safe_document_paths(
    state: MutableMapping[str, object], project_id: str,
) -> list[str]:
    """Accept only regular files in ``save_uploads``' exact root/token layout."""

    token = state.get("_general_upload_session_token")
    if not isinstance(token, str):
        raise AIInputError("분석할 업로드 문서가 없습니다.")
    root = session_storage_root()
    paths: list[str] = []
    for document in list_documents(state, project_id):
        raw_path = document.get("path")
        if not isinstance(raw_path, str):
            continue
        try:
            resolved = validated_session_file(raw_path, token, root)
        except (OSError, RuntimeError, ValueError):
            continue
        if (
            resolved.suffix.lower() in {".pdf", ".pptx", ".xlsx"}
        ):
            paths.append(str(resolved))
    if not paths:
        raise AIInputError("분석할 업로드 문서가 없습니다.")
    return paths


def _equipment_value(equipment: object, name: str, default: object = None) -> object:
    if isinstance(equipment, Mapping):
        return equipment.get(name, default)
    return getattr(equipment, name, default)


def _identified_equipment(equipment: object) -> IdentifiedEquipment:
    if isinstance(equipment, IdentifiedEquipment):
        return equipment
    return IdentifiedEquipment(
        equipment_type=str(_equipment_value(equipment, "equipment_type", "")),
        equipment_label=str(
            _equipment_value(equipment, "equipment_label", _equipment_value(equipment, "name", ""))
        ),
        manufacturer=_optional_string(_equipment_value(equipment, "manufacturer")),
        model_name=_optional_string(_equipment_value(equipment, "model_name")),
        excerpts=[],
        new_supplier=_optional_string(_equipment_value(equipment, "new_supplier")),
        new_model_name=_optional_string(_equipment_value(equipment, "new_model_name")),
        remarks=_optional_string(_equipment_value(equipment, "remarks")),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_citations(
    factors: dict[str, dict], allowed_locations: Mapping[str, set[str]],
) -> dict[str, dict]:
    """Keep citation metadata short and tied to an actual parsed document."""

    sanitized: dict[str, dict] = {}
    for key, raw in factors.items():
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        source_doc = item.get("source_doc")
        normalized_doc = Path(source_doc).name if isinstance(source_doc, str) else None
        if (
            not normalized_doc
            or normalized_doc not in allowed_locations
            or len(normalized_doc) > 255
            or any(character in normalized_doc for character in "\r\n\x00")
        ):
            item.pop("source_doc", None)
            item.pop("source_page", None)
        else:
            item["source_doc"] = normalized_doc
            source_page = item.get("source_page")
            if isinstance(source_page, (int, float)) and not isinstance(source_page, bool):
                source_page = str(source_page)
            if (
                not isinstance(source_page, str)
                or len(source_page) > 80
                or any(character in source_page for character in "\r\n\x00")
                or source_page not in allowed_locations[normalized_doc]
            ):
                item.pop("source_page", None)
            else:
                item["source_page"] = source_page
        sanitized[key] = item
    return sanitized


def _factor_records(factors: dict[str, dict], scoring_result: object) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for item in scoring_result.items:
        raw = factors.get(item.key)
        source_doc = raw.get("source_doc") if isinstance(raw, dict) else None
        source_page = raw.get("source_page") if isinstance(raw, dict) else None
        value = (
            {key: val for key, val in raw.items() if key not in {"source_doc", "source_page"}}
            if isinstance(raw, dict) else raw
        )
        records[item.key] = {
            "label": item.label,
            "value": value,
            "source_doc": source_doc if isinstance(source_doc, str) else None,
            "source_page": source_page if isinstance(source_page, str) else None,
            "max_points": item.max_points,
            "earned_points": item.earned_points,
            "excluded": item.excluded,
            "reason": item.reason,
        }
    return records


def _safe_sources(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    sources: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        title, url = item.get("title"), item.get("url")
        if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"}:
            continue
        sources.append({"title": str(title or url), "url": url})
    return sources


def _stable_equipment_ids(existing: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (str(row.get("name", "")).strip().casefold(), str(row.get("equipment_type", "")).strip().casefold()): str(row["id"])
        for row in existing
        if isinstance(row.get("id"), str)
    }


def _assess_one(
    equipment_value: object, units: list[object], clients: object,
    allowed_locations: Mapping[str, set[str]], review_reason: str | None,
) -> dict[str, object]:
    equipment = _identified_equipment(equipment_value)
    criteria_loader = _injected_value(clients, "load_criteria", "criteria_loader", default=load_criteria)
    scoring = _injected_value(clients, "compute_score", "scoring", default=compute_score)
    reference_loader = _injected_value(
        clients, "load_reference_text", "reference_loader", default=load_reference_text,
    )
    factor_client = _injected_value(clients, "factor_client", "factors")
    opinion_client = _injected_value(clients, "opinion_client", "opinion")
    risk_client = _injected_value(clients, "risk_checklist_client", "risk", default=None)
    new_model_client = _injected_value(
        clients, "new_model_review_client", "new_model", default=None,
    )

    criteria = criteria_loader(equipment.equipment_type)
    raw_factors = factor_client.extract_factors(criteria, equipment, units)
    if not isinstance(raw_factors, dict):
        raw_factors = {}
    factors = _sanitize_citations(
        _sanitize_factors(criteria, raw_factors), allowed_locations,
    )
    scoring_result = scoring(criteria, factors)
    reference_text = reference_loader(equipment.equipment_type)
    opinion = opinion_client.generate_opinion(
        equipment, scoring_result, reference_text,
        remarks=equipment.remarks, review_reason=review_reason,
    )

    new_model_review = None
    detail_warnings: list[str] = []
    new_model_review_status = "not_requested"
    if new_model_client is not None and equipment.new_supplier and equipment.new_model_name:
        new_model_review_status = "complete"
        web_available = bool(_injected_value(
            clients, "new_model_web_available", default=True,
        ))
        limitation = None if web_available else "웹 검색을 사용할 수 없어 신규 모델 검토가 제한됩니다."
        try:
            candidate = new_model_client.review(
                equipment, equipment.new_supplier, equipment.new_model_name,
            )
            if isinstance(candidate, Mapping):
                new_model_review = {
                    "summary": str(candidate.get("summary", "")),
                    "sources": _safe_sources(candidate.get("sources")),
                    "web_research_available": web_available,
                    "limitation": limitation,
                }
            else:
                new_model_review_status = "failed"
                detail_warnings.append("신규 모델 검토를 완료하지 못했습니다.")
        except Exception:
            new_model_review_status = "failed"
            detail_warnings.append("신규 모델 검토를 완료하지 못했습니다.")
            new_model_review = {
                "summary": "신규 모델 검토를 완료하지 못했습니다.",
                "sources": [],
                "web_research_available": web_available,
                "limitation": limitation,
            }

    risks: list[str] = []
    risk_checklist_status = "not_requested"
    if risk_client is not None:
        risk_checklist_status = "complete"
        try:
            candidate_risks = risk_client.generate_checklist(
                equipment, scoring_result, reference_text, factor_inputs=factors,
                new_model_review=new_model_review, remarks=equipment.remarks,
                review_reason=review_reason,
            )
            if isinstance(candidate_risks, list):
                risks = [str(risk) for risk in candidate_risks if isinstance(risk, str)]
            else:
                risk_checklist_status = "failed"
                detail_warnings.append("리스크 체크리스트를 완료하지 못했습니다.")
        except Exception:
            risk_checklist_status = "failed"
            detail_warnings.append("리스크 체크리스트를 완료하지 못했습니다.")

    extracted_factors = _factor_records(factors, scoring_result)
    report = {
        "score": scoring_result.total_score,
        "evaluated_max_points": scoring_result.evaluated_max_points,
        "pass_threshold": scoring_result.pass_threshold,
        "needs_replacement": scoring_result.needs_replacement,
        "factor_inputs": factors,
        "extracted_factors": extracted_factors,
        "technical_opinion": str(opinion),
        "new_model_review": new_model_review,
        "new_model_review_status": new_model_review_status,
        "risk_checklist": risks,
        "risk_checklist_status": risk_checklist_status,
        "analysis_warnings": detail_warnings,
    }
    return {
        "name": equipment.equipment_label,
        "equipment_type": equipment.equipment_type,
        "manufacturer": equipment.manufacturer or "",
        "model_name": equipment.model_name or "",
        "new_supplier": equipment.new_supplier,
        "new_model_name": equipment.new_model_name,
        "remarks": equipment.remarks,
        "status": "reviewed",
        "analysis_managed": True,
        "report": report,
        **report,
    }


def _run_analysis(
    state: MutableMapping[str, object], project_id: str, clients: object,
    *, review_reason: str | None, snapshot_after: bool,
) -> AnalysisOutcome:
    paths = _safe_document_paths(state, project_id)
    parser = _injected_value(clients, "parse_uploaded_files", "parser")
    extraction_client = _injected_value(clients, "extraction_client", "extraction")
    try:
        units = parser(paths)
        identified = extraction_client.identify_equipment(units)
    except Exception:
        raise AIServiceError(_AI_FAILED) from None
    if not isinstance(identified, list):
        raise AIServiceError(_AI_FAILED)
    if not identified:
        raise AIServiceError(_AI_FAILED)

    existing_ids = _stable_equipment_ids(list_equipment(state, project_id))
    allowed_documents = {Path(path).name for path in paths}
    allowed_locations: dict[str, set[str]] = {name: set() for name in allowed_documents}
    for unit in units:
        source_doc = Path(str(getattr(unit, "source_doc", ""))).name
        unit_label = getattr(unit, "unit_label", None)
        if (
            source_doc in allowed_locations
            and isinstance(unit_label, str)
            and len(unit_label) <= 80
            and not any(character in unit_label for character in "\r\n\x00")
        ):
            allowed_locations[source_doc].add(unit_label)
    successful_rows: list[dict[str, object]] = []
    failed: list[str] = []
    warnings: list[str] = []
    for raw_equipment in identified:
        label = str(_equipment_value(raw_equipment, "equipment_label", "설비"))
        try:
            row = _assess_one(
                raw_equipment, units, clients, allowed_locations, review_reason,
            )
        except Exception:
            failed.append(f"{label}: 분석하지 못했습니다.")
            continue
        stable_key = (str(row["name"]).strip().casefold(), str(row["equipment_type"]).strip().casefold())
        row_warnings = row.get("analysis_warnings", [])
        if isinstance(row_warnings, list):
            warnings.extend(f"{label}: {warning}" for warning in row_warnings)
        if stable_key in existing_ids:
            row["id"] = existing_ids.pop(stable_key)
        successful_rows.append(row)

    if identified and not successful_rows:
        raise AIServiceError(_AI_FAILED)

    equipment_ids = replace_project_equipment(
        state, project_id, successful_rows,
        preserve_unmanaged=True, preserve_stale=bool(failed),
    )
    for equipment_id, row in zip(equipment_ids, successful_rows):
        row["equipment_id"] = equipment_id
    report_data = {
        "generated_at": utc_timestamp(),
        "review_reason": review_reason,
        "total_equipment": len(successful_rows),
        "recommended_replacements": sum(
            1 for row in successful_rows if bool(row.get("needs_replacement"))
        ),
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "equipment_reports": successful_rows,
    }
    set_report_data(state, project_id, report_data)
    transition_project(state, project_id, "reviewed")
    version_id = (
        create_report_version(state, project_id, "AI 분석 완료") if snapshot_after else ""
    )
    return AnalysisOutcome(equipment_ids, failed, version_id, warnings)


def analyze_project(
    state: MutableMapping[str, object], project_id: str, api_key: str | None = None,
    model: str | None = None, tavily_api_key: str | None = None, clients: object | None = None,
) -> AnalysisOutcome:
    """Identify and assess all equipment found in a project's safe uploads."""

    resolved = _resolve_clients(clients, api_key, model, tavily_api_key)
    get_project(state, project_id)
    _safe_document_paths(state, project_id)
    _reserve_action(state)
    return _run_analysis(state, project_id, resolved, review_reason=None, snapshot_after=True)


def re_review_project(
    state: MutableMapping[str, object], project_id: str, reason: str,
    api_key: str | None = None, model: str | None = None,
    tavily_api_key: str | None = None, clients: object | None = None,
) -> AnalysisOutcome:
    """Snapshot the current report, then recalculate it with a review reason."""

    if not isinstance(reason, str) or not reason.strip():
        raise AIInputError("재검토 사유를 입력하세요.")
    resolved = _resolve_clients(clients, api_key, model, tavily_api_key)
    get_project(state, project_id)
    _safe_document_paths(state, project_id)
    _reserve_action(state)
    version_id = create_report_version(state, project_id, reason.strip())
    outcome = _run_analysis(
        state, project_id, resolved, review_reason=reason.strip(), snapshot_after=False,
    )
    return AnalysisOutcome(outcome.succeeded, outcome.failed, version_id, outcome.warnings)


def _chat_context_item(equipment: Mapping[str, object]) -> dict[str, object]:
    report = equipment.get("report")
    report_data = report if isinstance(report, Mapping) else equipment
    extracted = report_data.get("extracted_factors", {})
    return {
        "equipment_label": str(equipment.get("name", "")),
        "equipment_type": str(equipment.get("equipment_type", "")),
        "manufacturer": str(equipment.get("manufacturer", "")),
        "model_name": str(equipment.get("model_name", "")),
        "score": report_data.get("score", 0),
        "needs_replacement": bool(report_data.get("needs_replacement", False)),
        "technical_opinion": report_data.get("technical_opinion"),
        "discontinuation_status": equipment.get("discontinuation_status"),
        "extracted_factors": json.dumps(extracted, ensure_ascii=False),
    }


def answer_equipment_chat(
    state: MutableMapping[str, object], project_id: str, equipment_id: str, question: str,
    api_key: str | None = None, model: str | None = None,
    tavily_api_key: str | None = None, clients: object | None = None,
) -> ChatOutcome:
    """Answer a question and append an isolated two-turn equipment transcript."""

    if not isinstance(question, str) or not question.strip():
        raise AIInputError("질문을 입력하세요.")
    resolved = _resolve_clients(clients, api_key, model, tavily_api_key)
    project = get_project(state, project_id)
    equipment = next(
        (row for row in list_equipment(state, project_id) if row.get("id") == equipment_id), None,
    )
    if equipment is None:
        raise KeyError(f"Unknown equipment: {equipment_id}")
    history = list_chat_messages(state, project_id, equipment_id)
    _reserve_action(state)
    chatbot = _injected_value(resolved, "chatbot_client", "chatbot")
    context_project = dict(project)
    context_project.setdefault("pm_name", project.get("owner", ""))
    try:
        result = chatbot.answer(
            build_project_context(context_project, [_chat_context_item(equipment)]),
            history,
            question.strip(),
        )
        if not isinstance(result, Mapping) or not str(result.get("answer", "")).strip():
            raise ValueError
        answer = str(result["answer"]).strip()
        sources = _safe_sources(result.get("sources"))
    except Exception:
        raise AIServiceError(_AI_FAILED) from None

    append_chat_message(state, project_id, equipment_id, "user", question.strip())
    append_chat_message(state, project_id, equipment_id, "assistant", answer, sources)
    return ChatOutcome(answer, sources)
