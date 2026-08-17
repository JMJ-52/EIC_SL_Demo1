from __future__ import annotations

from lifecycle.assessment.llm import call_openai_json
from lifecycle.extraction.models import IdentifiedEquipment
from lifecycle.scoring import ScoringResult

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["opinion"],
    "properties": {"opinion": {"type": "string"}},
}


def _build_instructions(remarks: str | None, review_reason: str | None) -> str:
    return (
        "당신은 제철소 전기설비 노후교체 타당성을 검토하는 기술 전문가입니다. "
        "아래 설비의 채점 결과와 사내 참고자료를 근거로, 교체 타당성에 대한 기술적 의견을 "
        "한국어로 3~5문장으로 작성하세요. 확인필요로 표시된 항목이 있다면 추가 확인이 "
        "필요하다는 점을 명시하세요. 점수표에 없는 내용이라도 참고자료에 근거가 있다면 폭넓게 의견을 제시하세요."
        + (" 특이사항이 주어졌다면 반드시 반영하여 의견을 작성하세요." if remarks else "")
        + (" 재검토 요청 사유가 주어졌다면 그 사유를 반드시 반영하여 의견을 작성하세요." if review_reason else "")
    )


def _build_input_content(
    equipment: IdentifiedEquipment, scoring_result: ScoringResult, reference_text: str,
    remarks: str | None, review_reason: str | None,
) -> str:
    score_lines = [
        f"- {item.label}: 확인필요 (미평가)" if item.excluded else f"- {item.label}: {item.earned_points}/{item.max_points}점"
        for item in scoring_result.items
    ]
    judgement = "교체 고려" if scoring_result.needs_replacement else "교체 보류"
    remarks_block = f"\n\n[특이사항]\n{remarks}" if remarks else ""
    review_reason_block = f"\n\n[재검토 요청 사유]\n{review_reason}" if review_reason else ""
    return (
        f"[설비: {equipment.equipment_label} ({equipment.equipment_type})]\n"
        f"[공급사: {equipment.manufacturer or '미상'} / 모델: {equipment.model_name or '미상'}]\n"
        f"[채점 결과: 총점 {scoring_result.total_score}/{scoring_result.evaluated_max_points}"
        f"(평가된 항목 기준), 판정: {judgement}]\n"
        + "\n".join(score_lines)
        + f"\n\n[참고자료]\n{reference_text}{remarks_block}{review_reason_block}"
    )


class TechnicalOpinionClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json

    def generate_opinion(
        self, equipment: IdentifiedEquipment, scoring_result: ScoringResult, reference_text: str,
        remarks: str | None = None, review_reason: str | None = None,
    ) -> str:
        instructions = _build_instructions(remarks, review_reason)
        input_content = _build_input_content(equipment, scoring_result, reference_text, remarks, review_reason)
        payload = self._call_fn(self._api_key, self._model, instructions, input_content, _SCHEMA, "technical_opinion")
        opinion = (payload.get("opinion") or "").strip()
        if not opinion:
            raise ValueError("LLM returned an empty technical opinion")
        return opinion

