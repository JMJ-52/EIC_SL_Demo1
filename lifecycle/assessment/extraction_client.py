from __future__ import annotations

import base64
from dataclasses import replace

from lifecycle.assessment.llm import call_openai_json
from lifecycle.extraction.models import VALID_EQUIPMENT_TYPES, ExcerptRef, IdentifiedEquipment, ParsedUnit

_INSTRUCTIONS = (
    "당신은 제철소 전기설비 도면/자료에서 PLC, Drive, Motor 설비를 식별하는 어시스턴트입니다. "
    "제공된 문서 조각(텍스트 및 이미지)을 읽고, 등장하는 PLC/Drive/Motor 설비를 각각 식별하세요. "
    "확실하지 않은 필드는 null로 두세요."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["equipment"],
    "properties": {
        "equipment": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["equipment_type", "equipment_label", "manufacturer", "model_name", "excerpts"],
                "properties": {
                    "equipment_type": {"type": "string"},
                    "equipment_label": {"type": "string"},
                    "manufacturer": {"type": ["string", "null"]},
                    "model_name": {"type": ["string", "null"]},
                    "excerpts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["source_doc", "unit_label", "snippet"],
                            "properties": {
                                "source_doc": {"type": "string"},
                                "unit_label": {"type": "string"},
                                "snippet": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}

# Guardrails against sending an unbounded payload (request-size failures / API cost).
MAX_IMAGES_PER_REQUEST = 30
MAX_TEXT_CHARS_PER_UNIT = 4000

_TYPE_ALIASES = {"plc": "PLC", "drive": "Drive", "motor": "Motor"}


def _detect_image_mime(image_bytes: bytes) -> str | None:
    """Sniff an image's MIME type from its magic bytes.

    Returns None for formats the Vision API cannot accept (e.g. EMF/WMF, which
    PowerPoint frequently embeds); callers should skip those images.
    """
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def _build_input_content(units: list[ParsedUnit]) -> list[dict]:
    content: list[dict] = []
    images_added = 0
    for unit in units:
        header = f"[{unit.source_doc} / {unit.unit_label}]"
        text = unit.text
        if len(text) > MAX_TEXT_CHARS_PER_UNIT:
            text = text[:MAX_TEXT_CHARS_PER_UNIT] + "\n...[truncated]"
        content.append({"type": "input_text", "text": f"{header}\n{text}"})
        for image_bytes in unit.images:
            if images_added >= MAX_IMAGES_PER_REQUEST:
                break
            mime = _detect_image_mime(image_bytes)
            if mime is None:
                continue
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}"})
            images_added += 1
    return [{"role": "user", "content": content}]


def _parse_response(payload: dict) -> list[IdentifiedEquipment]:
    equipment_list = payload.get("equipment")
    if equipment_list is None:
        raise ValueError(f"LLM response is missing 'equipment' key: {payload!r}")

    results = []
    for entry in equipment_list:
        raw_type = entry.get("equipment_type")
        equipment_type = _TYPE_ALIASES.get(str(raw_type).strip().lower()) if raw_type else None
        if equipment_type is None:
            raise ValueError(
                f"LLM returned unknown equipment_type {raw_type!r}; expected one of {sorted(VALID_EQUIPMENT_TYPES)}"
            )
        excerpts = [
            ExcerptRef(source_doc=e["source_doc"], unit_label=e["unit_label"], snippet=e["snippet"])
            for e in entry.get("excerpts", [])
        ]
        results.append(
            IdentifiedEquipment(
                equipment_type=equipment_type,
                equipment_label=entry.get("equipment_label", ""),
                manufacturer=entry.get("manufacturer"),
                model_name=entry.get("model_name"),
                excerpts=excerpts,
            )
        )
    return results


def _filter_hallucinated_excerpts(
    equipment: list[IdentifiedEquipment], units: list[ParsedUnit]
) -> list[IdentifiedEquipment]:
    """Drop excerpt citations pointing at units that were never sent to the LLM."""
    known = {(u.source_doc, u.unit_label) for u in units}
    return [
        replace(item, excerpts=[e for e in item.excerpts if (e.source_doc, e.unit_label) in known])
        for item in equipment
    ]


class OpenAIExtractionClient:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o", call_fn=None):
        self._api_key = api_key
        self._model = model
        self._call_fn = call_fn or call_openai_json

    def identify_equipment(self, units: list[ParsedUnit]) -> list[IdentifiedEquipment]:
        if not units:
            return []
        input_content = _build_input_content(units)
        payload = self._call_fn(
            self._api_key, self._model, _INSTRUCTIONS, input_content, _SCHEMA, "equipment_identification"
        )
        return _filter_hallucinated_excerpts(_parse_response(payload), units)

