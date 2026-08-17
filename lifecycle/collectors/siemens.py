"""Siemens product phase-out notice collector.

Adapted from refer/module_scrapping_SIEMENS.py: renamed the entry point to
``collect`` and exposed each notice's source URL as ``공지링크``.
"""

from __future__ import annotations

import html
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Any

from .common import TARGETS, Deadline

PORTAL_SEARCH_URL = "https://sieportal.siemens.com/ko-kr/search"
PM_ORDER = {"PM400": 1, "PM410": 2, "PM490": 3, "PM500": 4}
PM_LABELS = {
    "PM400": "단종 예정 없음",
    "PM410": "단종 예정(양산 종료, 서비스 및 부품 지원)",
    "PM490": "단종 예정(제한적 서비스 및 부품 지원)",
    "PM500": "단종",
}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


class SiemensCollectionError(RuntimeError):
    """Raised for invalid input or unrecoverable public-site failures."""


@dataclass(frozen=True)
class Notice:
    title: str
    url: str


@dataclass(frozen=True)
class Milestone:
    status: str
    value: date
    precision: str
    sentence: str


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((" ".join(self._text).strip(), self._href))
            self._href = None
            self._text = []


def normalize_model(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


def normalize_product_family(model_name: str, target: str) -> str:
    """Return the display family used by the Siemens lifecycle JSON."""
    cleaned = " ".join(model_name.upper().split())
    if target == "PLC":
        match = re.search(r"S\s*7\s*[- ]?(\d{3})", cleaned)
        return f"S7-{match.group(1)}" if match else cleaned
    if target == "Drive":
        match = re.search(r"SINAMICS\s+([GSV]\d{2,3}(?:/[GSV]\d{2,3})*)", cleaned)
        return f"SINAMICS {match.group(1)}" if match else cleaned
    return cleaned


def _request(url: str, retries: int = 2) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "LifecyclePreview/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, UnicodeError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(attempt + 1)
    raise SiemensCollectionError(f"SIEMENS 공식 사이트 요청 실패: {last_error}")


def _score(model_name: str, text: str) -> int:
    model = normalize_model(model_name)
    candidate = normalize_model(text)
    if model and model in candidate:
        return 100
    chunks = re.findall(r"[A-Z]+\d+[A-Z0-9-]*|S7-?\d+|SINAMICS", model_name.upper())
    matched = sum(normalize_model(chunk) in candidate for chunk in chunks if len(chunk) >= 3)
    return min(90, matched * 30)


def search_pm_notices(model_name: str) -> list[Notice]:
    """Find model-related public support-document links from the PM410 search."""
    query = urllib.parse.urlencode({
        "scope": "knowledgebase",
        "Type": "siePortal",
        "SearchTerm": "PM410",
        "SortingOption": "Relevance",
    })
    parser = _LinkParser()
    parser.feed(_request(f"{PORTAL_SEARCH_URL}?{query}"))
    found: dict[str, Notice] = {}
    for title, href in parser.links:
        url = urllib.parse.urljoin(PORTAL_SEARCH_URL, html.unescape(href))
        if "support.industry.siemens.com/cs/document/" not in url or _score(model_name, title) == 0:
            continue
        found[url] = Notice(title=title, url=url)
    return sorted(found.values(), key=lambda notice: _score(model_name, notice.title), reverse=True)


def _text_from_html(page: str) -> str:
    parser = _TextParser()
    parser.feed(page)
    return parser.text()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _parse_date(raw: str) -> tuple[date, str] | None:
    raw = raw.strip()
    iso = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if iso:
        return date(*map(int, iso.groups())), "day"
    dmy = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if dmy:
        day, month, year = map(int, dmy.groups())
        return date(year, month, day), "day"
    month_first = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s*(\d{4})", raw)
    if month_first and month_first.group(1).lower() in MONTHS:
        month, day, year = month_first.groups()
        return date(int(year), MONTHS[month.lower()], int(day)), "day"
    day_first = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)[,]?\s*(\d{4})", raw)
    if day_first and day_first.group(2).lower() in MONTHS:
        day, month, year = day_first.groups()
        return date(int(year), MONTHS[month.lower()], int(day)), "day"
    month_only = re.search(r"\b(\d{1,2})/(\d{4})\b", raw)
    if month_only:
        month, year = map(int, month_only.groups())
        return date(year, month, 28), "month"
    return None


DATE_PATTERN = (
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s*\d{4}|\b\d{1,2}/\d{4}\b"
)


def _milestones(text: str) -> list[Milestone]:
    found: list[Milestone] = []
    for sentence in _sentences(text):
        for status in PM_ORDER:
            if not re.search(rf"\b(?:P\.?M\.?|M\.?){status[2:]}\b", sentence, re.I):
                continue
            date_match = re.search(DATE_PATTERN, sentence)
            if not date_match:
                continue
            parsed = _parse_date(date_match.group(0))
            if parsed:
                value, precision = parsed
                found.append(Milestone(status, value, precision, sentence))
    return found


def _ko_date(value: date, precision: str) -> str:
    return f"{value.year}년 {value.month}월 말" if precision == "month" else f"{value.year}년 {value.month}월 {value.day}일"


def _entry_date(text: str) -> str | None:
    match = re.search(r"Entry date:\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", text, re.I)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    return date(year, month, day).isoformat()


def _stale_remark(published: str | None) -> str | None:
    if not published:
        return None
    return "공지 10년 이상 경과, 공급사 문의 필요" if (date.today() - date.fromisoformat(published)).days >= 3652 else None


def _build_item(model_name: str, target: str, notice: Notice) -> tuple[dict[str, Any] | None, str]:
    text = _text_from_html(_request(notice.url))
    milestones = _milestones(text)
    if not milestones:
        return None, "공지 본문에서 PM 단계와 날짜를 함께 확인하지 못함"

    applicable = [milestone for milestone in milestones if milestone.value <= date.today()]
    if not applicable:
        return None, "현재 날짜 기준으로 적용된 PM 단계가 없음"
    current = max(applicable, key=lambda milestone: (PM_ORDER[milestone.status], milestone.value))
    evidence_ko = (
        f"공식 공지에서 {normalize_product_family(model_name, target)}의 "
        f"{current.status} 적용일은 {_ko_date(current.value, current.precision)}로 확인된다."
    )
    return {
        "공급사": "SIEMENS",
        "대상": target,
        "모델명": normalize_product_family(model_name, target),
        "단종여부": PM_LABELS[current.status],
        "단종시기": _ko_date(current.value, current.precision),
        "적용_상태": current.status,
        "게시일": _entry_date(text),
        "비고": _stale_remark(_entry_date(text)),
        "근거문장": evidence_ko,
        "근거문장(원문)": current.sentence,
        "공지링크": notice.url,
    }, ""


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["대상"], normalize_model(item["모델명"]))
        current = result.get(key)
        if current is None or PM_ORDER[item["적용_상태"]] > PM_ORDER[current["적용_상태"]]:
            result[key] = item
    return sorted(result.values(), key=lambda item: (item["대상"], item["모델명"]))


def collect(model_name: str, target: str, deadline: Deadline | None = None) -> dict[str, Any]:
    """Collect a Siemens lifecycle JSON preview for one model; never writes a DB.

    Work stops after ``deadline`` (default common.MODEL_DEADLINE_SECONDS).
    """
    target = target.strip().upper() if target.strip().upper() == "PLC" else target.strip().title()
    if target not in TARGETS:
        raise SiemensCollectionError("대상은 PLC, Drive, Motor 중 하나여야 합니다.")
    if not model_name or not model_name.strip():
        raise SiemensCollectionError("모델명은 필수입니다.")

    budget = deadline or Deadline()
    notices = search_pm_notices(model_name)
    if not notices:
        return {
            "items": [],
            "review": {"status": "review_required", "message": "검색 결과에서 모델 관련 SIEMENS 공식 공지를 확인하지 못했습니다.", "candidates_checked": 0, "excluded": []},
        }

    items: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    timed_out = False
    for notice in notices[:20]:
        if budget.expired():
            timed_out = True
            excluded.append({"title": notice.title, "reason": f"모델당 수집 시간 상한({budget.seconds:.0f}초) 초과로 미확인"})
            continue
        try:
            item, reason = _build_item(model_name, target, notice)
        except SiemensCollectionError as error:
            excluded.append({"title": notice.title, "reason": str(error)})
            continue
        if item:
            items.append(item)
        else:
            excluded.append({"title": notice.title, "reason": reason})
        time.sleep(0.15)

    items = _deduplicate(items)
    status = "ready" if items else "review_required"
    message = "SIEMENS 공식 공지 기반 JSON 미리보기를 생성했습니다." if items else "공식 근거를 충분히 확인하지 못했습니다. 등록 전 검토가 필요합니다."
    if timed_out:
        status = "review_required"
        message += f" (모델당 수집 시간 상한 {budget.seconds:.0f}초를 넘겨 일부 공지를 확인하지 못했습니다.)"
    return {
        "items": items,
        "review": {
            "status": status, "message": message, "timed_out": timed_out,
            "candidates_checked": len(notices), "excluded": excluded,
        },
    }

