from __future__ import annotations

from dataclasses import dataclass, field

from lifecycle.criteria_loader import CriteriaItem, CriteriaSet


@dataclass
class ItemResult:
    key: str
    label: str
    max_points: float
    earned_points: float | None
    excluded: bool
    reason: str | None = None


@dataclass
class ScoringResult:
    equipment_type: str
    total_score: float
    pass_threshold: float
    needs_replacement: bool
    # Sum of max_points across only the items that were actually evaluated
    # (excluding 확인필요 items), so a consumer can tell 69/95 from 69/40.
    evaluated_max_points: float
    items: list[ItemResult] = field(default_factory=list)


def _score_categorical(item: CriteriaItem, data: dict) -> float:
    value = data["value"]
    for option in item.options:
        if option.value == value:
            return option.points
    raise ValueError(f"'{value}' is not a valid option for '{item.key}'")


def _score_linear_capped(item: CriteriaItem, data: dict) -> float:
    years = data["years"]
    points = years * (item.points_per_year or 1)
    return min(max(points, 0), item.max_points)


def _score_sum_subfactors(item: CriteriaItem, data: dict) -> float:
    flags = data["flags"]
    total = 0.0
    for sub_factor in item.sub_factors:
        val = flags.get(sub_factor.key, False)
        if not isinstance(val, bool):
            raise ValueError(f"sub-factor '{sub_factor.key}' of '{item.key}' must be a bool, got {val!r}")
        if val is True:
            total += sub_factor.points
    return min(total, item.max_points)


def _score_repair_history(item: CriteriaItem, data: dict) -> float:
    rewind_count = data["rewind_count"]
    overhaul_count = data["overhaul_count"]
    if rewind_count < 0:
        raise ValueError(f"rewind_count must not be negative, got {rewind_count!r}")
    if overhaul_count < 0:
        raise ValueError(f"overhaul_count must not be negative, got {overhaul_count!r}")
    if rewind_count <= 0:
        base = 0
    elif rewind_count == 1:
        base = 20
    elif rewind_count == 2:
        base = 25
    else:
        base = 30
    total = base + overhaul_count * 10
    return min(total, item.max_points)


def _score_operating_hours(item: CriteriaItem, data: dict) -> float:
    years = data["years"]
    daily_hours = data["daily_hours"]
    points = years * daily_hours / 24
    return min(max(points, 0), item.max_points)


def _score_spare_parts_ratio(item: CriteriaItem, data: dict) -> float:
    held = data["held_quantity"]
    installed = data["installed_quantity"]
    if installed <= 0:
        raise ValueError("installed_quantity must be greater than 0")
    points = item.max_points - (held / installed) * item.max_points
    return min(max(points, 0), item.max_points)


def _score_failure_count(item: CriteriaItem, data: dict) -> float:
    annual_failures = data["annual_failures"]
    if annual_failures < 0:
        raise ValueError(f"annual_failures must not be negative, got {annual_failures!r}")
    base = min((annual_failures / 12) * item.max_points, item.max_points)
    bonus = 0.0
    if annual_failures > 12:
        bonus_cap = item.bonus_cap or 0
        bonus = min((annual_failures - 12) * 0.5, bonus_cap)
    return base + bonus


def _score_direct_score(item: CriteriaItem, data: dict) -> float:
    value = data["value"]
    return min(max(value, 0), item.max_points)


_RULES = {
    "categorical": _score_categorical,
    "linear_capped": _score_linear_capped,
    "sum_subfactors": _score_sum_subfactors,
    "repair_history": _score_repair_history,
    "operating_hours": _score_operating_hours,
    "spare_parts_ratio": _score_spare_parts_ratio,
    "failure_count": _score_failure_count,
    "direct_score": _score_direct_score,
}


def compute_score(criteria: CriteriaSet, factor_inputs: dict[str, dict]) -> ScoringResult:
    item_results = []
    total = 0.0
    evaluated_max = 0.0

    for item in criteria.items:
        data = factor_inputs.get(item.key)
        # Both None (key absent) and {} (extractor found the field but could not
        # parse a value) count as missing data -> 확인필요.
        if not data:
            item_results.append(
                ItemResult(key=item.key, label=item.label, max_points=item.max_points,
                           earned_points=None, excluded=True, reason="확인필요")
            )
            continue

        rule_fn = _RULES[item.rule]
        earned = rule_fn(item, data)
        total += earned
        evaluated_max += item.max_points
        item_results.append(
            ItemResult(key=item.key, label=item.label, max_points=item.max_points,
                       earned_points=earned, excluded=False)
        )

    unknown_keys = set(factor_inputs) - {item.key for item in criteria.items}
    if unknown_keys:
        raise ValueError(f"unknown factor keys for {criteria.equipment_type}: {sorted(unknown_keys)}")

    return ScoringResult(
        equipment_type=criteria.equipment_type,
        total_score=total,
        pass_threshold=criteria.pass_threshold,
        needs_replacement=total >= criteria.pass_threshold,
        evaluated_max_points=evaluated_max,
        items=item_results,
    )

