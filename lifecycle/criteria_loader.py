from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

CRITERIA_DIR = Path(__file__).parent / "criteria"

# Whitelist of supported equipment types. Validated before any path is built,
# because equipment_type is caller-supplied (ultimately from an AI extraction step).
SUPPORTED_EQUIPMENT_TYPES = frozenset({"motor", "plc", "drive"})


@dataclass
class CriteriaOption:
    value: str
    label: str
    points: float


@dataclass
class SubFactor:
    key: str
    label: str
    points: float


@dataclass
class CriteriaItem:
    key: str
    label: str
    max_points: float
    rule: str
    options: list[CriteriaOption] = field(default_factory=list)
    sub_factors: list[SubFactor] = field(default_factory=list)
    bonus_cap: float | None = None
    points_per_year: float | None = None
    # True for items decided elsewhere (단종여부 comes from the 공급사/모델명
    # lookup), so the UI locks them unless the reviewer opts into manual entry.
    auto_determined: bool = False


@dataclass
class CriteriaSet:
    equipment_type: str
    max_score: float
    pass_threshold: float
    items: list[CriteriaItem]


def load_criteria(equipment_type: str) -> CriteriaSet:
    normalized = equipment_type.lower()
    if normalized not in SUPPORTED_EQUIPMENT_TYPES:
        raise ValueError(f"Unknown equipment type: {equipment_type}")
    return _load_criteria_cached(normalized)


@lru_cache(maxsize=8)
def _load_criteria_cached(normalized: str) -> CriteriaSet:
    path = CRITERIA_DIR / f"{normalized}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown equipment type: {normalized}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    items = []
    for raw_item in raw["items"]:
        options = [CriteriaOption(**opt) for opt in raw_item.get("options", [])]
        sub_factors = [SubFactor(**sf) for sf in raw_item.get("sub_factors", [])]
        items.append(
            CriteriaItem(
                key=raw_item["key"],
                label=raw_item["label"],
                max_points=raw_item["max_points"],
                rule=raw_item["rule"],
                options=options,
                sub_factors=sub_factors,
                bonus_cap=raw_item.get("bonus_cap"),
                points_per_year=raw_item.get("points_per_year"),
                auto_determined=bool(raw_item.get("auto_determined", False)),
            )
        )

    return CriteriaSet(
        equipment_type=raw["equipment_type"],
        max_score=raw["max_score"],
        pass_threshold=raw["pass_threshold"],
        items=items,
    )

