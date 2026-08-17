"""Shared constants and helpers for supplier lifecycle collectors."""

from __future__ import annotations

import re
import time
import unicodedata

TARGETS = {"PLC", "Drive", "Motor"}
WEB_SUPPLIERS = {"ABB", "SIEMENS", "HITACHI"}
PDF_SUPPLIERS = {"TMEIC", "TOSHIBA", "MELCO"}

# 모델 1건 수집에 허용하는 최대 시간. 상한이 없으면 PDF 20건 × 60초 타임아웃 ×
# 재시도 3회가 겹칠 때 한 모델이 한 시간을 잡아먹고, 야간 정기 수집이 아침까지
# 끝나지 않는다. 상한에 걸리면 그때까지 확보한 근거로 결과를 만들고 중단 사실을
# review 에 남긴다.
MODEL_DEADLINE_SECONDS = 120.0


def _normalized_name(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9가-힣]+", "", unicodedata.normalize("NFKC", value or "").upper())


def relevant_items(model_name: str, items: list[dict]) -> list[dict]:
    """Keep only what actually describes the registered model.

    One lookup drags in notices for neighbouring products — 97 ABB models
    produced 182 items, 85 of them about some other drive. Treating those as this
    model's status turns another product's end-of-life date into this model's
    alert. Collectors sort most-relevant-first, so item 0 is this model's notice;
    it is kept even when the notice words the subject differently (so nothing is
    lost), and the rest only when the name matches what is registered.
    """
    if not items:
        return []
    registered = _normalized_name(model_name)
    return [items[0]] + [
        item for item in items[1:] if _normalized_name(item.get("모델명")) == registered
    ]


class Deadline:
    """Wall-clock budget for one model's collection."""

    def __init__(self, seconds: float = MODEL_DEADLINE_SECONDS) -> None:
        self.seconds = seconds
        self._ends_at = time.monotonic() + seconds

    def expired(self) -> bool:
        return time.monotonic() >= self._ends_at

    def remaining(self) -> float:
        return max(0.0, self._ends_at - time.monotonic())

