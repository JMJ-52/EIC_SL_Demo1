from __future__ import annotations

from pathlib import Path

REFERENCE_DIR = Path(__file__).parent
_SUPPORTED_TYPES = {"motor", "plc", "drive"}


def load_reference_text(equipment_type: str) -> str:
    normalized = equipment_type.lower()
    if normalized not in _SUPPORTED_TYPES:
        raise ValueError(f"No reference text for equipment type: {equipment_type}")
    path = REFERENCE_DIR / f"{normalized}.md"
    return path.read_text(encoding="utf-8")

