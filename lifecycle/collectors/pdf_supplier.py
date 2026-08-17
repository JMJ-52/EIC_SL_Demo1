"""TMEIC, TOSHIBA, MELCO PDF lifecycle preview collector.

Adapted from refer/module_scrapping_TMEIC.py: split the original
``collect_pdf_lifecycle`` into ``_extract_page_texts`` (the only part that
touches the filesystem/pypdf) and ``_build_result`` (pure parsing logic),
so tests can exercise the parsing rules with plain strings instead of a
real PDF file. Every item now carries ``"공지링크": None`` because these
suppliers are announced via uploaded PDFs, not a public web notice.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - surfaced as a review result
    PdfReader = None  # type: ignore[assignment,misc]

DATE_CELL = re.compile(r"^(\d{4})/(\d{1,2})$")
ROW_DATE = re.compile(r"^\d{4}/\d{1,2}$")


class PdfPreviewError(RuntimeError):
    """Raised for invalid input or an unreadable PDF."""


def _clean(value: str | None) -> str:
    return " ".join((value or "").replace(" S peed", " Speed").split())


def _supplier(value: str) -> str | None:
    upper = _clean(value).upper()
    if upper.startswith("TMEIC"):
        return "TMEIC"
    if upper.startswith("TOSHIBA"):
        return "TOSHIBA"
    if upper.startswith("MELCO"):
        return "MELCO"
    return None


def _parse_month_end(value: str) -> date | None:
    match = DATE_CELL.fullmatch(_clean(value))
    if not match:
        return None
    year, month = map(int, match.groups())
    return date(year, month, calendar.monthrange(year, month)[1])


def _ko_date(value: date | None) -> str | None:
    return f"{value.year}년 {value.month}월 {value.day}일" if value else None


def _target_for_page(page_text: str, equipment: str) -> str | None:
    if "Level-1 PLC, Automation" in page_text:
        return "PLC"
    if "Drive System" in page_text:
        return "Motor" if "motor" in equipment.lower() else "Drive"
    return None


def _notice_date(supplied: str | None) -> str | None:
    if supplied:
        try:
            return date.fromisoformat(supplied).isoformat()
        except ValueError as error:
            raise PdfPreviewError("notice_date는 YYYY-MM-DD 형식이어야 합니다.") from error
    return None


def _stale_remark(published: str | None) -> str | None:
    if not published:
        return None
    return "공지 10년 이상 경과, 공급사 문의 필요" if (date.today() - date.fromisoformat(published)).days >= 3652 else None


def _classify(parts_raw: str, service_raw: str) -> tuple[str, str | None, str] | None:
    """Return lifecycle label, displayed date, and Korean evidence.

    ``None`` means that only one deadline was extracted and the row must be
    reviewed rather than guessed.
    """
    parts_end = _parse_month_end(parts_raw)
    service_end = _parse_month_end(service_raw)
    today = date.today()
    if parts_end and service_end:
        if today < parts_end:
            return (
                "단종 예정(양산 종료, 서비스 및 부품 지원)",
                _ko_date(parts_end),
                f"5열 부품 공급 종료일 {_ko_date(parts_end)} 이전이므로 양산 종료 전 단계입니다.",
            )
        if today <= service_end:
            return (
                "단종 예정(제한적 서비스 및 부품 지원)",
                _ko_date(service_end),
                f"5열 부품 공급 종료일 이후이고 6열 보수 대응 종료일 {_ko_date(service_end)} 이전이므로 제한적 지원 단계입니다.",
            )
        return "단종", _ko_date(service_end), f"6열 보수 대응 종료일 {_ko_date(service_end)}이 지났습니다."

    normalized = f"{_clean(parts_raw)} {_clean(service_raw)}".lower()
    if "terminated" in normalized:
        return "단종", None, "표의 지원 상태가 Terminated로 명시되어 있습니다."
    if not parts_end and not service_end and ("current model" in normalized or normalized.strip(" -") == ""):
        return "단종 예정 없음", None, "5열과 6열에 종료일이 없고 Current Model로 표시되어 있습니다."
    return None


def _source_row(supplier: str, equipment: str, model: str, start: str, parts: str, service: str) -> str:
    return (
        f"Manufacture: {supplier}; Equipment name: {equipment}; Series: {model}; "
        f"Production Start: {start or '[blank]'}; Spare Parts Supply Until: {parts or '[blank]'}; "
        f"Maintenance Service Period Until: {service or '[blank]'}"
    )


def _row_columns(line: str) -> list[str]:
    """Split pypdf layout-mode cells without relying on fixed page widths."""
    return [_clean(part) for part in re.split(r" {3,}", line) if _clean(part)]


def _extract_page_rows(page_text: str) -> list[dict[str, str]]:
    target = _target_for_page(page_text, "")
    if not target:
        return []
    rows: list[dict[str, str]] = []
    previous_equipment = ""
    for line in page_text.splitlines():
        columns = _row_columns(line)
        if len(columns) < 4:
            continue
        supplier = _supplier(columns[0])
        if not supplier:
            continue
        production_index = next((index for index, value in enumerate(columns) if ROW_DATE.fullmatch(value)), None)
        if production_index is None or production_index < 2:
            continue
        model = columns[production_index - 1]
        equipment = " ".join(columns[1:production_index - 1]) or previous_equipment
        if not equipment or not model:
            continue
        previous_equipment = equipment
        trailing = columns[production_index + 1:]
        parts = trailing[0] if trailing else ""
        service = trailing[1] if len(trailing) > 1 else ""
        row_target = _target_for_page(page_text, equipment)
        if not row_target:
            continue
        rows.append({
            "supplier": supplier,
            "target": row_target,
            "equipment": equipment,
            "model": model,
            "production": columns[production_index],
            "parts": parts,
            "service": service,
        })
    return rows


def _item_from_row(row: dict[str, str], published: str | None) -> tuple[dict[str, Any] | None, str | None]:
    classified = _classify(row["parts"], row["service"])
    original = _source_row(row["supplier"], row["equipment"], row["model"], row["production"], row["parts"], row["service"])
    if not classified:
        return None, f"{row['model']}: 5열 또는 6열 종료일을 신뢰성 있게 판독하지 못함 ({original})"
    lifecycle, period, reason = classified
    return {
        "공급사": row["supplier"],
        "대상": row["target"],
        "모델명": row["model"],
        "단종여부": lifecycle,
        "단종시기": period,
        "적용_상태": None if lifecycle == "단종 예정 없음" else "단종 공지 발생",
        "게시일": published,
        "비고": _stale_remark(published),
        "근거문장": f"공식 PDF에서 {row['model']}의 {reason}",
        "근거문장(원문)": original,
        "공지링크": None,
    }, None


def _resolve_conflicts(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[(item["공급사"], item["대상"], item["모델명"].upper())].append(item)
    accepted: list[dict[str, Any]] = []
    review: list[str] = []
    for key, candidates in grouped.items():
        values = {(entry["단종여부"], entry["단종시기"], entry["근거문장(원문)"]) for entry in candidates}
        if len(values) > 1:
            review.append(f"{key[2]}: 동일 모델에서 상충된 상태 또는 날짜가 발견되어 자동 선택하지 않음")
        else:
            accepted.append(candidates[0])
    return sorted(accepted, key=lambda item: (item["공급사"], item["대상"], item["모델명"])), review


def _build_result(page_texts: list[str], notice_date: str | None) -> dict[str, Any]:
    """Extract every TMEIC/TOSHIBA/MELCO lifecycle row found in the PDF.

    Supplier, target, and model are all read from the table itself, so the
    caller does not need to know in advance which models the PDF covers.
    """
    published = _notice_date(notice_date)
    rows = [row for text in page_texts for row in _extract_page_rows(text)]
    if not rows:
        return {"items": [], "review": {"status": "not_found", "message": "PDF에서 공급사 단종 표 행을 찾지 못했습니다.", "pages_checked": len(page_texts), "excluded": []}}

    candidates: list[dict[str, Any]] = []
    excluded: list[str] = []
    for row in rows:
        item, reason = _item_from_row(row, published)
        if item:
            candidates.append(item)
        elif reason:
            excluded.append(reason)
    items, conflicts = _resolve_conflicts(candidates)
    excluded.extend(conflicts)
    if not items:
        status = "review_required"
        message = "공식 PDF에서 행은 찾았지만 등록 가능한 상태·날짜·근거를 모두 확인하지 못했습니다."
    elif excluded:
        status = "review_required"
        message = "일부 행에 검토가 필요합니다. 생성된 항목도 관리자 확인 후 등록하세요."
    else:
        status = "ready"
        message = "공식 PDF 근거가 있는 JSON 미리보기를 생성했습니다."
    return {"items": items, "review": {"status": status, "message": message, "pages_checked": len(page_texts), "rows_matched": len(rows), "excluded": excluded}}


def _extract_page_texts(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]


def collect_pdf(pdf_path: str | Path, notice_date: str | None = None) -> dict[str, Any]:
    """Create PDF-grounded preview data for every TMEIC/TOSHIBA/MELCO model in the PDF.

    Each returned item carries its own 공급사/대상/모델명, read from the table
    rows themselves. Performs no DB, network, or email operation.
    """
    path = Path(pdf_path)
    if not path.is_file():
        raise PdfPreviewError(f"PDF 파일을 찾을 수 없습니다: {path}")
    if path.suffix.lower() != ".pdf":
        raise PdfPreviewError("PDF 파일만 분석할 수 있습니다.")
    if PdfReader is None:
        return {"items": [], "review": {"status": "error", "message": "pypdf가 필요합니다.", "excluded": []}}

    try:
        page_texts = _extract_page_texts(path)
    except Exception as error:  # pypdf exposes several parser-specific errors
        return {"items": [], "review": {"status": "error", "message": f"PDF 텍스트 추출 실패: {error}", "excluded": []}}

    return _build_result(page_texts, notice_date)

