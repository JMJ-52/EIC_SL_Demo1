from __future__ import annotations

from lifecycle.assessment.llm import call_openai_json
from lifecycle.criteria_loader import CriteriaItem, CriteriaSet
from lifecycle.extraction.models import IdentifiedEquipment, ParsedUnit
from lifecycle.scoring import _RULES

# Upper bound on how much text from a single parsed unit is sent to the LLM,
# so a pathologically long page cannot blow up the request payload.
MAX_TEXT_CHARS_PER_UNIT = 4000


def _item_value_schema(item: CriteriaItem) -> dict:
    if item.rule == "categorical":
        return {"value": {"type": "string", "enum": [o.value for o in item.options]}}
    if item.rule == "linear_capped":
        return {"years": {"type": "number"}}
    if item.rule == "sum_subfactors":
        return {
            "flags": {
                "type": "object",
                "additionalProperties": False,
                "required": [sf.key for sf in item.sub_factors],
                "properties": {sf.key: {"type": "boolean"} for sf in item.sub_factors},
            }
        }
    if item.rule == "repair_history":
        return {"rewind_count": {"type": "integer"}, "overhaul_count": {"type": "integer"}}
    if item.rule == "operating_hours":
        return {"years": {"type": "number"}, "daily_hours": {"type": "number"}}
    if item.rule == "spare_parts_ratio":
        return {"held_quantity": {"type": "number"}, "installed_quantity": {"type": "number"}}
    if item.rule == "failure_count":
        return {"annual_failures": {"type": "number"}}
    raise ValueError(f"Unknown rule type: {item.rule}")


def _build_factor_schema(criteria: CriteriaSet) -> dict:
    # `direct_score` items are deliberately excluded: that rule uses whatever
    # number it is given as the score, so asking the LLM for one would let the
    # LLM score the equipment. Those items stay 확인필요 for a human to fill in.
    scoreable_items = [item for item in criteria.items if item.rule != "direct_score"]
    properties = {}
    for item in scoreable_items:
        value_props = _item_value_schema(item)
        properties[item.key] = {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": [*value_props.keys(), "source_doc", "source_page"],
            "properties": {**value_props, "source_doc": {"type": ["string", "null"]}, "source_page": {"type": ["string", "null"]}},
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["factors"],
        "properties": {
            "factors": {
                "type": "object",
                "additionalProperties": False,
                "required": [item.key for item in scoreable_items],
                "properties": properties,
            }
        },
    }


def _build_instructions(criteria: CriteriaSet) -> str:
    return (
        f"당신은 {criteria.equipment_type} 설비의 노후교체 판정을 위해 자료에서 채점 인자를 "
        "추출하는 어시스턴트입니다. 아래 문서 조각들에서 각 항목의 값을 찾아 채우세요. "
        "자료에서 확인할 수 없는 항목은 해당 항목 전체를 null로 응답하세요 (추측 금지). "
        "각 값에는 근거가 된 자료의 위치를 대괄호 표기([파일명 / 위치])와 함께 "
        "source_doc/source_page로 기록하세요. 근거를 찾지 못한 항목은 source_doc/source_page도 null로 두세요."
    )


def _build_input_content(equipment: IdentifiedEquipment, units: list[ParsedUnit]) -> str:
    excerpt_block = "\n\n".join(
        f"[{u.source_doc} / {u.unit_label}]\n{u.text[:MAX_TEXT_CHARS_PER_UNIT]}" for u in units
    )
    return f"[설비: {equipment.equipment_label} ({equipment.equipment_type})]\n\n{excerpt_block}"


def _sanitize_factors(criteria: CriteriaSet, raw_factors: dict, *, allow_direct_score: bool = False) -> dict:
    """Keep only values that the actual scoring rules accept as-is.

    Reuses the engine's own rule functions as the validator (single source of
    truth): if a rule function raises on the LLM's value, that item is dropped
    and compute_score will mark it 확인필요 naturally.

    `direct_score` items (e.g. 외관검사) are dropped by default because the
    AI must never be allowed to invent a visual-inspection score - see
    `_build_factor_schema`. The manual-input path in pipeline.py is the one
    exception: a human typing that value in is the ONLY way it can ever be
    filled, so that caller passes allow_direct_score=True to let a validated
    value through instead of silently discarding it.
    """
    sanitized = {}
    for item in criteria.items:
        if item.rule == "direct_score" and not allow_direct_score:
            continue
        value = raw_factors.get(item.key)
        if not value:
            continue
        try:
            _RULES[item.rule](item, value)
        except Exception:
            # Deliberately broad: this validator sits directly on untrusted LLM
            # output, so *any* failure inside a rule function means "reject this
            # value and leave the item 확인필요" - never a crash.
            continue
        sanitized[item.key] = value
    return sanitized


class FactorExtractionClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json

    def extract_factors(self, criteria: CriteriaSet, equipment: IdentifiedEquipment, units: list[ParsedUnit]) -> dict:
        known_excerpts = {(e.source_doc, e.unit_label) for e in equipment.excerpts}
        matched_units = [u for u in units if (u.source_doc, u.unit_label) in known_excerpts]
        if not matched_units:
            # The identification step is allowed to return an equipment with no
            # excerpt citations at all (the schema does not require them), and
            # it regularly does for single-document uploads. Bailing out here
            # made *every* factor come back 확인필요 even though the document
            # plainly contained the values - the "factor 값이 입력이 안 된다"
            # symptom. Fall back to the whole uploaded set instead: it is
            # already scoped to this project, and the instructions name the
            # specific equipment being scored.
            matched_units = units
        if not matched_units:
            return {}

        instructions = _build_instructions(criteria)
        input_content = _build_input_content(equipment, matched_units)
        schema = _build_factor_schema(criteria)
        payload = self._call_fn(self._api_key, self._model, instructions, input_content, schema, "factor_extraction")
        raw_factors = payload.get("factors")
        if not isinstance(raw_factors, dict):
            return {}
        return _sanitize_factors(criteria, {k: v for k, v in raw_factors.items() if v is not None})

