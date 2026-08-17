from __future__ import annotations

import json

from lifecycle.assessment.llm import call_openai_json
from lifecycle.assessment.tavily import search_web
from lifecycle.criteria_loader import load_criteria
from lifecycle.judgment import classify_item
# factor_display only depends on criteria_loader, so importing it here does not
# create a cycle with lifecycle.webapp.main (which imports this module).
from lifecycle.webapp import factor_display

_ROUTE_INSTRUCTIONS = (
    "당신은 노후설비 타당성 검토 보고서에 대해 답변하는 어시스턴트입니다. "
    "아래 프로젝트 데이터를 근거로 답변하세요. 데이터만으로 답할 수 없는 질문"
    "(예: 유사 사례, 공급사의 후속 모델 추천 등 외부 정보가 필요한 경우)에는 웹 검색이 필요하다고 판단하세요."
)

_ROUTE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["needs_search", "search_query", "answer"],
    "properties": {
        "needs_search": {"type": "boolean"},
        "search_query": {"type": ["string", "null"]},
        "answer": {"type": ["string", "null"]},
    },
}

_FINAL_INSTRUCTIONS = (
    "당신은 노후설비 타당성 검토 보고서에 대해 답변하는 어시스턴트입니다. "
    "아래 프로젝트 데이터와 웹 검색 결과를 근거로 사용자 질문에 답변하세요. 검색 결과를 인용할 때는 출처를 명시하세요."
)

_FINAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer"],
    "properties": {"answer": {"type": "string"}},
}


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(이전 대화 없음)"
    lines = []
    for turn in history:
        role = "사용자" if turn.get("role") == "user" else "어시스턴트"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)


def _build_route_input(project_context: str, history: list[dict], question: str) -> str:
    return f"[프로젝트 데이터]\n{project_context}\n\n[이전 대화]\n{_format_history(history)}\n\n[질문]\n{question}"


def _build_final_input(project_context: str, history: list[dict], question: str, results: list[dict]) -> str:
    search_block = (
        "\n\n".join(f"- {r['title']} ({r['url']})\n  {r['content'][:500]}" for r in results)
        if results else "(검색 결과 없음)"
    )
    return (
        f"[프로젝트 데이터]\n{project_context}\n\n[이전 대화]\n{_format_history(history)}\n\n"
        f"[질문]\n{question}\n\n[웹 검색 결과]\n{search_block}"
    )


class ChatbotClient:
    def __init__(
        self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None,
        search_fn=None, tavily_api_key: str | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json
        self._search_fn = search_fn or search_web
        self._tavily_api_key = tavily_api_key

    def answer(self, project_context: str, history: list[dict], question: str) -> dict:
        route_input = _build_route_input(project_context, history, question)
        route_payload = self._call_fn(self._api_key, self._model, _ROUTE_INSTRUCTIONS, route_input, _ROUTE_SCHEMA, "chat_route")

        if not route_payload.get("needs_search"):
            answer_text = (route_payload.get("answer") or "").strip()
            if not answer_text:
                raise ValueError("LLM did not provide a direct answer")
            return {"answer": answer_text, "sources": []}

        query = route_payload.get("search_query") or question
        # A missing Tavily key means web search isn't configured, not that the
        # question is unanswerable - treat it the same as an empty search
        # result instead of calling self._search_fn (which would raise) so the
        # chatbot still answers as best it can from the project data alone.
        results = self._search_fn(self._tavily_api_key, query) if self._tavily_api_key else []

        final_input = _build_final_input(project_context, history, question, results)
        final_payload = self._call_fn(self._api_key, self._model, _FINAL_INSTRUCTIONS, final_input, _FINAL_SCHEMA, "chat_final")
        answer_text = (final_payload.get("answer") or "").strip()
        if not answer_text:
            raise ValueError("LLM did not provide a final answer")

        sources = [{"title": r["title"], "url": r["url"]} for r in results]
        return {"answer": answer_text, "sources": sources}


# Handing the model bare "18/20점" pairs made it invent the measurements behind
# them: it read a score as the quantity ("18년 사용"), and read a full-marks
# categorical item as good news ("수리 가능") when in this scale high points mean
# "more in need of replacement". Both are cured by sending the same value + how it
# was scored + where it came from that the report screen already shows, plus an
# explicit note on which way the scale runs.
_SCALE_NOTE = (
    "[평가 척도 안내]\n"
    "- 점수는 '노후도·교체 필요성'을 나타냅니다. 점수가 높을수록 교체 필요성이 크고, 낮을수록 상태가 양호합니다.\n"
    "- 각 항목은 '실측값 → 배점 산식 → 획득점수/만점' 순으로 제공됩니다. 실측값과 점수를 혼동하지 마세요.\n"
    "- '확인필요'는 값이 없어 채점에서 제외된 항목입니다. 0점은 값이 확인되었고 그 값이 0점에 해당한다는"
    " 뜻이며, 확인필요와 다릅니다.\n"
    "- 데이터에 없는 수치는 추정하지 말고 '데이터에 없다'고 답하세요."
)


def _format_score(value: float | int | None) -> str:
    """Round for display - the raw float reads as false precision (77.41666666666667)."""
    if value is None:
        return "-"
    rounded = round(float(value), 1)
    return str(int(rounded)) if float(rounded).is_integer() else f"{rounded:g}"


def build_project_context(project: dict, equipment_items: list[dict]) -> str:
    lines = [
        _SCALE_NOTE,
        "",
        f"투자코드: {project['investment_code']}",
        f"사업명: {project['project_name']}",
        f"담당PM: {project.get('pm_name') or '-'}",
        f"상태: {project['status']}",
        "",
    ]
    for item in equipment_items:
        verdict = "교체 고려" if item["needs_replacement"] else "교체 보류"
        factors = json.loads(item["extracted_factors"])
        try:
            criteria = load_criteria(item["equipment_type"])
        except ValueError:
            # Unknown equipment type: fall back to labels + points rather than
            # failing the whole chat turn.
            criteria = None
        criteria_by_key = {c.key: c for c in criteria.items} if criteria else {}

        lines.append(f"- 설비: {item['equipment_label']} ({item['equipment_type']})")
        lines.append(f"  제조사/모델명: {item.get('manufacturer') or '-'} / {item.get('model_name') or '-'}")
        score_line = f"  종합점수: {_format_score(item['score'])}점 / 100점"
        if criteria:
            has_excluded = any(f["excluded"] for f in factors.values())
            judgment = classify_item(item["score"], has_excluded, criteria.pass_threshold)
            score_line += (f" (합격기준 {_format_score(criteria.pass_threshold)}점,"
                           f" 판정: {judgment}, {verdict})")
        else:
            score_line += f" ({verdict})"
        lines.append(score_line)
        if item.get("discontinuation_status"):
            lines.append(f"  단종여부: {item['discontinuation_status']}")
        if item.get("technical_opinion"):
            lines.append(f"  기술의견: {item['technical_opinion']}")

        lines.append("  [평가항목]")
        for key, factor in factors.items():
            value_display, score_basis = factor_display.describe(
                criteria_by_key.get(key), factor.get("value"), factor["earned_points"], factor["excluded"],
            )
            source = ""
            if factor.get("source_doc"):
                cited = [factor["source_doc"], factor.get("source_page") or ""]
                source = " [출처: " + " ".join(p for p in cited if p) + "]"
            lines.append(f"  · {factor['label']}: 실측값 {value_display} → {score_basis}{source}")
    return "\n".join(lines)

