from __future__ import annotations

from lifecycle.assessment.llm import call_openai_json
from lifecycle.assessment.tavily import search_web
from lifecycle.extraction.models import IdentifiedEquipment

_INSTRUCTIONS = (
    "당신은 제철소 전기설비 교체 검토를 지원하는 기술 조사 담당자입니다. "
    "아래 기존 설비 정보와 현장이 희망하는 신규 교체 대상(공급사/모델명), 그리고 그 신규 모델에 대한 "
    "웹 검색 결과를 보고 다음을 2~4문장의 한국어로 요약하세요: "
    "(1) 검색 결과상 실재하는 모델인지, (2) 단종 예정이나 단종 이력이 있는지, "
    "(3) 기존 설비와 규격/사양이 달라지는 부분이 있는지. "
    "검색 결과가 부족해 판단할 수 없는 부분은 판단할 수 없다고 명시하세요."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}


def _build_search_query(new_supplier: str, new_model_name: str) -> str:
    return f"{new_supplier} {new_model_name} 사양 단종"


def _build_input_content(equipment: IdentifiedEquipment, new_supplier: str, new_model_name: str, results: list[dict]) -> str:
    search_block = (
        "\n\n".join(f"- {r['title']} ({r['url']})\n  {r['content'][:500]}" for r in results)
        if results else "(검색 결과 없음)"
    )
    return (
        f"[기존 설비: {equipment.equipment_label} ({equipment.equipment_type})]\n"
        f"[기존 공급사: {equipment.manufacturer or '미상'} / 기존 모델: {equipment.model_name or '미상'}]\n"
        f"[희망 신규 대상: {new_supplier} / {new_model_name}]\n\n"
        f"[웹 검색 결과]\n{search_block}"
    )


class NewModelReviewClient:
    def __init__(
        self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None,
        search_fn=None, tavily_api_key: str | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json
        self._search_fn = search_fn or search_web
        self._tavily_api_key = tavily_api_key

    def review(self, equipment: IdentifiedEquipment, new_supplier: str, new_model_name: str) -> dict:
        query = _build_search_query(new_supplier, new_model_name)
        results = self._search_fn(self._tavily_api_key, query)

        input_content = _build_input_content(equipment, new_supplier, new_model_name, results)
        payload = self._call_fn(self._api_key, self._model, _INSTRUCTIONS, input_content, _SCHEMA, "new_model_review")
        summary = (payload.get("summary") or "").strip()
        if not summary:
            raise ValueError("LLM did not provide a summary")

        sources = [{"title": r["title"], "url": r["url"]} for r in results]
        return {"summary": summary, "sources": sources}

