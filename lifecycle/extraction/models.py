from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedUnit:
    source_doc: str
    unit_label: str
    text: str
    images: list[bytes] = field(default_factory=list)


@dataclass
class ExcerptRef:
    source_doc: str
    unit_label: str
    snippet: str


VALID_EQUIPMENT_TYPES = {"PLC", "Drive", "Motor"}


@dataclass
class IdentifiedEquipment:
    equipment_type: str
    equipment_label: str
    manufacturer: str | None
    model_name: str | None
    excerpts: list[ExcerptRef] = field(default_factory=list)
    new_supplier: str | None = None
    new_model_name: str | None = None
    remarks: str | None = None
    factor_inputs: dict[str, dict] | None = None

