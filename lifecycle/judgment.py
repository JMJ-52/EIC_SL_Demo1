from __future__ import annotations

import json


def factor_has_excluded(extracted_factors_json: str) -> bool:
    factors = json.loads(extracted_factors_json)
    return any(factor["excluded"] for factor in factors.values())


def classify_item(score: float, has_excluded: bool, pass_threshold: float) -> str:
    if has_excluded:
        return "보완필요"
    if score >= pass_threshold:
        return "적정"
    return "부적정"


def classify_project(item_classifications: list[str]) -> str | None:
    if not item_classifications:
        return None
    if "보완필요" in item_classifications:
        return "보완필요"
    if all(c == "적정" for c in item_classifications):
        return "적정"
    if all(c == "부적정" for c in item_classifications):
        return "부적정"
    return "조건부"

