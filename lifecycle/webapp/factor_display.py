"""Human-readable rendering of a scored Factor for the report/history tables.

The stored `extracted_factors` records keep raw machine values ("years": 2.75,
"not_discontinued"), which is right for scoring but unreadable in a report. This
module turns each one into:

* `value_display` - the value with its unit ("2.75년 / 1일 8시간", "미단종")
* `score_basis`   - how that value became the score ("2.75 × 8 ÷ 24 = 0.9점"),
                    so a reviewer can check the arithmetic instead of taking
                    the number on trust.

The formulas mirror the rule functions in lifecycle/scoring.py; keep the two in
step if a rule ever changes.
"""
from __future__ import annotations

from lifecycle.criteria_loader import CriteriaItem


def _num(value: object) -> str:
    """Format a number without a trailing '.0' ("8" not "8.0", "2.75" stays)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return f"{round(float(value), 2):g}"


def _points(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{round(float(value), 1):g}"


def _option_label(item: CriteriaItem, raw: object) -> str:
    for option in item.options:
        if option.value == raw:
            return option.label
    return str(raw)


def _option_points(item: CriteriaItem, raw: object) -> float | None:
    for option in item.options:
        if option.value == raw:
            return option.points
    return None


def describe(item: CriteriaItem | None, value: object, earned_points: float | None, excluded: bool) -> tuple[str, str]:
    """Return (value_display, score_basis) for one scored factor."""
    if excluded or value is None:
        return "확인필요", "값이 없어 채점에서 제외 (확인필요)"
    if item is None:
        return str(value), "-"

    rule = item.rule
    max_points = item.max_points

    if rule == "operating_hours":
        years = value.get("years")
        daily = value.get("daily_hours")
        display = f"{_num(years)}년 / 1일 {_num(daily)}시간"
        basis = (f"{_num(years)} × {_num(daily)} ÷ 24 = {_points(earned_points)}점"
                 f" (최대 {_num(max_points)}점)")
        return display, basis

    if rule == "spare_parts_ratio":
        held = value.get("held_quantity")
        installed = value.get("installed_quantity")
        display = f"보유 {_num(held)}대 / 설치 {_num(installed)}대"
        basis = (f"{_num(max_points)} − ({_num(held)}/{_num(installed)} × {_num(max_points)})"
                 f" = {_points(earned_points)}점 (예비품이 많을수록 낮은 점수)")
        return display, basis

    if rule == "failure_count":
        failures = value.get("annual_failures")
        display = f"연간 {_num(failures)}건"
        basis = f"{_num(failures)}/12 × {_num(max_points)} = {_points(earned_points)}점"
        if item.bonus_cap and isinstance(failures, (int, float)) and failures > 12:
            basis += f" (12건 초과분 0.5점/건 가산, 최대 +{_num(item.bonus_cap)}점)"
        return display, basis

    if rule == "linear_capped":
        years = value.get("years")
        per_year = item.points_per_year or 1
        display = f"{_num(years)}년"
        basis = f"{_num(years)}년 × {_num(per_year)}점 = {_points(earned_points)}점 (최대 {_num(max_points)}점)"
        return display, basis

    if rule == "repair_history":
        rewind = value.get("rewind_count")
        overhaul = value.get("overhaul_count")
        display = f"리와인드 {_num(rewind)}회 / 오버홀 {_num(overhaul)}회"
        if not isinstance(rewind, (int, float)) or rewind <= 0:
            base = 0
        elif rewind == 1:
            base = 20
        elif rewind == 2:
            base = 25
        else:
            base = 30
        basis = (f"리와인드 {_num(rewind)}회 기준 {base}점 + 오버홀 {_num(overhaul)}회 × 10점"
                 f" = {_points(earned_points)}점 (최대 {_num(max_points)}점)")
        return display, basis

    if rule == "categorical":
        label = _option_label(item, value.get("value"))
        points = _option_points(item, value.get("value"))
        others = ", ".join(f"{o.label} {_num(o.points)}점" for o in item.options)
        basis = f"'{label}' 선택 → {_points(points if points is not None else earned_points)}점 (배점: {others})"
        return label, basis

    if rule == "sum_subfactors":
        flags = value.get("flags") or {}
        chosen = [sf for sf in item.sub_factors if flags.get(sf.key)]
        display = ", ".join(sf.label for sf in chosen) if chosen else "해당 없음"
        if chosen:
            summed = " + ".join(f"{sf.label} {_num(sf.points)}점" for sf in chosen)
            basis = f"{summed} = {_points(earned_points)}점 (최대 {_num(max_points)}점)"
        else:
            basis = f"해당 항목 없음 = 0점 (최대 {_num(max_points)}점)"
        return display, basis

    if rule == "direct_score":
        raw = value.get("value")
        display = f"{_num(raw)}점"
        basis = f"육안 점검 결과 직접 입력 → {_points(earned_points)}점 (최대 {_num(max_points)}점)"
        return display, basis

    return str(value), "-"

