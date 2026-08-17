from __future__ import annotations

from lifecycle.assessment.llm import call_openai_json
from lifecycle.extraction.models import IdentifiedEquipment
from lifecycle.scoring import ScoringResult

_INSTRUCTIONS = (
    "당신은 제철소 전기설비 노후교체 프로젝트의 리스크를 점검하는 기술 전문가입니다. "
    "아래 설비 정보, 채점 결과, (있는 경우) 신규 대상 검토 결과, (있는 경우) 특이사항, "
    "(있는 경우) 재검토 요청 사유를 근거로, "
    "이 설비를 실제로 교체할 때 실무진이 챙겨야 할 리스크를 체크리스트 형태로 뽑아내세요. "
    "반드시 입력값에 실제 근거가 있는 리스크만 포함하세요 - 근거 없는 일반론적인 리스크는 포함하지 마세요. "
    "리스크가 없다고 판단되면 빈 배열을 반환해도 됩니다. "
    "각 항목은 한국어 한 문장으로, 무엇을 확인/준비해야 하는지 구체적으로 작성하세요."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["risks"],
    "properties": {"risks": {"type": "array", "items": {"type": "string"}}},
}


def _format_factor_values(factor_inputs: dict) -> str:
    if not factor_inputs:
        return "(제공된 팩터 값 없음)"
    lines = []
    for key, raw in factor_inputs.items():
        value = raw.get("value", raw) if isinstance(raw, dict) else raw
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _build_input_content(
    equipment: IdentifiedEquipment, scoring_result: ScoringResult, reference_text: str,
    factor_inputs: dict | None, new_model_review: dict | None, remarks: str | None, review_reason: str | None,
) -> str:
    score_lines = [
        f"- {item.label}: 확인필요 (미평가)" if item.excluded else f"- {item.label}: {item.earned_points}/{item.max_points}점"
        for item in scoring_result.items
    ]
    judgement = "교체 고려" if scoring_result.needs_replacement else "교체 보류"
    factor_values_block = _format_factor_values(factor_inputs or {})
    new_model_block = f"\n\n[신규 대상 검토 결과]\n{new_model_review.get('summary', '')}" if new_model_review else ""
    remarks_block = f"\n\n[특이사항]\n{remarks}" if remarks else ""
    review_reason_block = f"\n\n[재검토 요청 사유]\n{review_reason}" if review_reason else ""
    return (
        f"[설비: {equipment.equipment_label} ({equipment.equipment_type})]\n"
        f"[공급사: {equipment.manufacturer or '미상'} / 모델: {equipment.model_name or '미상'}]\n"
        f"[신규 대상 공급사: {equipment.new_supplier or '없음'} / 신규 대상 모델: {equipment.new_model_name or '없음'}]\n"
        f"[채점 결과: 총점 {scoring_result.total_score}/{scoring_result.evaluated_max_points}"
        f"(평가된 항목 기준), 판정: {judgement}]\n"
        + "\n".join(score_lines)
        + f"\n\n[팩터 실제 값]\n{factor_values_block}\n\n[참고자료]\n{reference_text}"
        + f"{new_model_block}{remarks_block}{review_reason_block}"
    )


class RiskChecklistClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json

    def generate_checklist(
        self, equipment: IdentifiedEquipment, scoring_result: ScoringResult, reference_text: str,
        factor_inputs: dict | None = None, new_model_review: dict | None = None,
        remarks: str | None = None, review_reason: str | None = None,
    ) -> list[str]:
        input_content = _build_input_content(
            equipment, scoring_result, reference_text, factor_inputs, new_model_review, remarks, review_reason,
        )
        payload = self._call_fn(self._api_key, self._model, _INSTRUCTIONS, input_content, _SCHEMA, "risk_checklist")
        risks = payload.get("risks")
        if not isinstance(risks, list) or not all(isinstance(r, str) for r in risks):
            raise ValueError(f"LLM risk checklist 'risks' is not a list of strings: {payload!r}")
        return risks

