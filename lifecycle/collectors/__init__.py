"""Dispatch entry point for the three web-collectible suppliers."""

from __future__ import annotations

from typing import Any, Callable

from . import abb, hitachi, siemens
from .common import Deadline

WEB_COLLECTORS: dict[str, Callable[[str, str, Deadline | None], dict[str, Any]]] = {
    "ABB": abb.collect,
    "SIEMENS": siemens.collect,
    "HITACHI": hitachi.collect,
}


def collect(supplier: str, model_name: str, target: str, deadline: Deadline | None = None) -> dict[str, Any]:
    """Run one supplier's collector. `deadline` caps the wall clock for this model."""
    try:
        fn = WEB_COLLECTORS[supplier]
    except KeyError as exc:
        raise ValueError(f"자동 수집을 지원하지 않는 공급사입니다: {supplier}") from exc
    return fn(model_name, target, deadline)

