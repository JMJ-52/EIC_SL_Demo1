"""HITACHI public production-end notice collector.

Adapted from refer/module_scrapping.py: renamed the entry point to
``collect`` and exposed the source page as ``공지링크`` on every item.
Creates preview data only; the caller is responsible for review/approval
before anything is written to an application DB.
"""

from __future__ import annotations

import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from typing import Any

from .common import TARGETS, Deadline

SOURCES = {
    "PLC": "https://www.hitachi-ies.co.jp/products/plc/stop/index.htm",
    "Drive": "https://www.hitachi-ies.co.jp/products/inv/stop/index.html",
}

MODEL_KO = {
    "Webコントローラ": "웹 컨트롤러",
    "EH-150シリーズ": "EH-150 시리즈",
    "MICRO-EHシリーズ": "마이크로-EH 시리즈",
    "H-302/702/1002/2002/4010シリーズ": "H-302/702/1002/2002/4010 시리즈",
    "H-200/250/252シリーズ": "H-200/250/252 시리즈",
    "EMシリーズ": "EM 시리즈",
    "Eシリーズ": "E 시리즈",
    "ECシリーズ": "EC 시리즈",
    "高周波インバータSJH700": "고주파 인버터 SJH700",
    "NE-S1シリーズ": "NE-S1 시리즈",
    "WJ200シリーズ": "WJ200 시리즈",
    "SJ700シリーズ": "SJ700 시리즈",
    "L700シリーズ": "L700 시리즈",
    "X200シリーズ": "X200 시리즈",
    "SJH300シリーズ": "SJH300 시리즈",
    "L100シリーズ単相100V級": "L100 시리즈 (단상 100V급)",
    "L300Pシリーズ": "L300P 시리즈",
    "J500シリーズ": "J500 시리즈",
    "SJ200シリーズ": "SJ200 시리즈",
    "SJ300シリーズ三相200V級(全機種)三相400V級(全機種)": "SJ300 시리즈 (3상 200V급 및 3상 400V급 전체 모델)",
    "L200シリーズ": "L200 시리즈",
    "SJ100シリーズ": "SJ100 시리즈",
    "L100シリーズ三相200V級三相400V級単相200V級": "L100 시리즈 (3상 200V급, 3상 400V급 및 단상 200V급)",
    "J300シリーズ": "J300 시리즈",
    "J100シリーズ": "J100 시리즈",
    "J200シリーズ": "J200 시리즈",
    "L300シリーズ": "L300 시리즈",
    "HFC-VWS3(A)シリーズ": "HFC-VWS3(A) 시리즈",
}


UNMAPPED_REMARK = "한국어 모델명 미확정, 공식 표기 원문 사용"
MONTH_ONLY_REMARK = "공식 표기가 월 단위(일자 미기재)"


class HitachiCollectionError(RuntimeError):
    """Raised for invalid input or an unrecoverable official-site error."""


class _TableParser(HTMLParser):
    """Dependency-free extractor for visible HTML table cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self._table is None:
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def normalize_model(value: str) -> str:
    """Normalize model spelling while retaining identifier digits and letters."""
    value = unicodedata.normalize("NFKC", value).upper()
    return re.sub(r"[^A-Z0-9가-힣]+", "", value)


def _compact(value: str) -> str:
    return " ".join(value.split())


def _request(url: str, retries: int = 2) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "LifecyclePreview/1.0"})
    error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read()
                declared = re.search(br"charset=[\"']?([A-Za-z0-9_-]+)", body[:4096], re.I)
                if declared:
                    charset = declared.group(1).decode("ascii")
                return body.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(attempt + 1)
    raise HitachiCollectionError(f"HITACHI 공식 사이트 요청 실패: {error}")


def _find_notice_table(page: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(page)
    for table in parser.tables:
        if not table:
            continue
        header = " ".join(table[0])
        if "シリーズ名" in header and "生産終了時期" in header:
            return table
    raise HitachiCollectionError("공식 페이지에서 생산 종료 기종 표를 식별하지 못했습니다.")


def _page_reference_date(page: str) -> str | None:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日現在", page)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


_END_DATE_PATTERN = r"(\d{4})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?(末)?"


def _ko_end_date(raw: str) -> str | None:
    match = re.search(_END_DATE_PATTERN, raw)
    if not match:
        return None
    year, month, day, end = match.groups()
    if day:
        return f"{int(year)}년 {int(month)}월 {int(day)}일"
    if end:
        return f"{int(year)}년 {int(month)}월 말"
    # 공식 표가 "2019年3月"처럼 월만 적은 경우. 예전에는 None 을 돌려줘 단종시기가
    # 비었고, 일자로 적힌 기존 기준값과 영원히 어긋나 매번 검토 대상이 됐다. 날짜를
    # 지어내지 않고 월 단위 그대로 남긴다 — lifecycle.normalize 가 월 표기를 그 달
    # 말일로 환산하므로 같은 사실끼리는 정상 비교된다.
    return f"{int(year)}년 {int(month)}월"


def _is_month_only(raw: str) -> bool:
    """공식 표가 연·월만 적고 일자도 '末'도 없는가."""
    match = re.search(_END_DATE_PATTERN, raw)
    return bool(match) and not match.group(3) and not match.group(4)


def _ko_date_text(raw: str) -> str:
    match = re.search(r"(\d{4})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?(末)?", raw)
    if not match:
        return raw
    year, month, day, end = match.groups()
    if day:
        return f"{int(year)}년 {int(month)}월 {int(day)}일"
    return f"{int(year)}년 {int(month)}월 말" if end else f"{int(year)}년 {int(month)}월"


def _korean_model(raw_model: str) -> str | None:
    return MODEL_KO.get(raw_model) or MODEL_KO.get(re.sub(r"\s+", "", raw_model))


def _rows_for_target(target: str) -> tuple[list[dict[str, str]], str | None]:
    page = _request(SOURCES[target])
    table = _find_notice_table(page)
    rows: list[dict[str, str]] = []
    for row in table[1:]:
        if len(row) < 2:
            continue
        raw_model, raw_end = _compact(row[0]), _compact(row[1])
        if not raw_model or not raw_end:
            continue
        rows.append({"raw_model": raw_model, "raw_end": raw_end})
    return rows, _page_reference_date(page)


def _related(query: str, raw_model: str, korean_model: str) -> bool:
    """Does this table row describe the model that was asked for?

    Matching anywhere inside the candidate made "J200" pull in WJ200 and SJ200 —
    different inverter families — so a J200 lookup reported WJ200's end date. The
    model code has to start the candidate; a trailing variant ("SJ700" → SJ700B)
    is still a match, a different prefix is not.
    """
    normalized = normalize_model(query)
    if not normalized:
        return False
    candidates = {normalize_model(raw_model), normalize_model(korean_model)}
    if normalized in candidates:
        return True
    return len(normalized) >= 4 and any(candidate.startswith(normalized) for candidate in candidates)


def _core_model(value: str) -> str:
    """Drop the series suffix so "SJ700 시리즈" and raw "SJ700シリーズ" both read as SJ700."""
    return normalize_model(value).replace("시리즈", "")


def _subject_rank(query: str, model: str) -> int:
    """Exact matches first so items[0] is the model that was asked for."""
    normalized_query = _core_model(query)
    normalized_model = _core_model(model)
    if not normalized_query or not normalized_model:
        return 0
    if normalized_query == normalized_model:
        return 300
    if normalized_query in normalized_model:
        return 200
    return 100 if normalized_model in normalized_query else 0


def _stale_remark(published: str | None) -> str | None:
    if not published:
        return None
    try:
        published_date = date.fromisoformat(published)
    except ValueError:
        return None
    return "공지 10년 이상 경과, 공급사 문의 필요" if (date.today() - published_date).days >= 3652 else None


def collect(model_name: str, target: str, deadline: Deadline | None = None) -> dict[str, Any]:
    """Collect HITACHI preview items for one model without changing a DB.

    One page fetch does the whole job here, so ``deadline`` only guards against
    starting when the model's budget is already spent; it exists to keep the
    three collectors interchangeable.
    """
    target = target.strip().upper() if target.strip().upper() == "PLC" else target.strip().title()
    if target not in TARGETS:
        raise HitachiCollectionError("대상은 PLC, Drive, Motor 중 하나여야 합니다.")
    if not model_name or not model_name.strip():
        raise HitachiCollectionError("model_name은 필수입니다.")
    if target == "Motor":
        return {"items": [], "review": {"status": "review_required", "message": "Motor의 재현 가능한 HITACHI 공식 생산 종료 공지 경로를 확인하지 못했습니다.", "source_url": None, "candidates_checked": 0, "excluded": []}}
    if deadline is not None and deadline.expired():
        return {"items": [], "review": {"status": "review_required", "message": f"모델당 수집 시간 상한({deadline.seconds:.0f}초)을 이미 초과해 수집을 시작하지 않았습니다.", "timed_out": True, "source_url": SOURCES[target], "candidates_checked": 0, "excluded": []}}

    rows, published = _rows_for_target(target)
    items: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for row in rows:
        korean_model = _korean_model(row["raw_model"])
        # MODEL_KO is a hand-maintained table, so a genuinely new production-end
        # notice — exactly what a periodic check exists to catch — has no Korean
        # name yet. Surface it under its original name with a remark instead of
        # dropping it; a reviewer completes the translation on approval.
        display_model = korean_model or _compact(row["raw_model"])
        if not _related(model_name, row["raw_model"], display_model):
            if not korean_model:
                excluded.append({"model": row["raw_model"], "reason": "검증된 한국어 모델명 변환 없음"})
            continue
        end_date = _ko_end_date(row["raw_end"])
        remarks = [
            remark for remark in (
                _stale_remark(published),
                None if korean_model else UNMAPPED_REMARK,
                MONTH_ONLY_REMARK if _is_month_only(row["raw_end"]) else None,
            ) if remark
        ]
        items.append({
            "공급사": "HITACHI",
            "대상": target,
            "모델명": display_model,
            "단종여부": "단종",
            "단종시기": end_date,
            "적용_상태": "단종 공지 발생",
            "게시일": published,
            "비고": "; ".join(remarks) or None,
            "근거문장": f"HITACHI 공식 생산 종료 기종 표에 {display_model} 항목이 포함되어 있으며 생산 종료 시기는 {_ko_date_text(row['raw_end'])}이다.",
            "근거문장(원문)": f"{row['raw_model']} | {row['raw_end']}",
            "공지링크": SOURCES[target],
        })
    items.sort(key=lambda item: -_subject_rank(model_name, item["모델명"]))
    if not items:
        return {"items": [], "review": {"status": "review_required", "message": "입력 모델이 HITACHI 공식 생산 종료 표에 없거나, 등록 가능한 공식 근거를 확보하지 못했습니다.", "source_url": SOURCES[target], "candidates_checked": len(rows), "excluded": excluded}}
    missing_date = any(item["단종시기"] is None for item in items)
    unmapped = any(UNMAPPED_REMARK in (item["비고"] or "") for item in items)
    month_only = any(MONTH_ONLY_REMARK in (item["비고"] or "") for item in items)
    if missing_date:
        message = "상태는 확인됐지만 일부 항목의 공식 표에 생산 종료 시기가 없어 등록 전 검토가 필요합니다."
    elif unmapped:
        message = "공식 표에서 찾았지만 한국어 모델명이 확정되지 않아 원문 표기를 사용했습니다. 등록 전 모델명 확인이 필요합니다."
    elif month_only:
        message = "공식 표가 일자 없이 월까지만 표기해 월 단위로 기록했습니다. 등록 전 확인이 필요합니다."
    else:
        message = "HITACHI 공식 생산 종료 표 기반 JSON 미리보기를 생성했습니다."
    review_required = missing_date or unmapped or month_only
    return {
        "items": items,
        "review": {
            "status": "review_required" if review_required else "ready",
            "message": message,
            "source_url": SOURCES[target],
            "candidates_checked": len(rows),
            "excluded": excluded,
        },
    }

