"""ABB Library life-cycle collector.

Adapted from refer/module_scrapping_ABB.py: renamed the entry point to
``collect``, renamed the category-id lookup to ``CATEGORY_IDS`` to avoid
shadowing ``collectors.common.TARGETS``, and exposed each notice's PDF URL
as ``공지링크``.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - surfaced as a review result
    PdfReader = None  # type: ignore[assignment,misc]

from .common import TARGETS, Deadline

SEARCH_URL = "https://discoveryapi.library.abb.com/api/public/documents"
CATEGORY_IDS = {
    "PLC": "9AAC177033",
    "Drive": "9AAC100211",
    "Motor": "9AAC133417",
}
STATE_ORDER = {"Active": 1, "Classic": 2, "Limited": 3, "Obsolete": 4}
STATE_LABEL = {
    "Active": "단종 예정 없음",
    "Classic": "단종 예정(양산 종료, 서비스 및 부품 지원)",
    "Limited": "단종 예정(제한적 서비스 및 부품 지원)",
    "Obsolete": "단종",
}
NEXT_STATE = {"Active": "Classic", "Classic": "Limited", "Limited": "Obsolete"}
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


NOTICE_CACHE_TTL_SECONDS = 3600
_NOTICE_CACHE: dict[str, tuple[float, list["Notice"]]] = {}


class AbbCollectionError(RuntimeError):
    """Raised for invalid input or a non-recoverable ABB collection failure."""


@dataclass(frozen=True)
class Notice:
    document_id: str
    revision: str
    language: str
    title: str
    published: str | None
    url: str
    suffix: str


def normalize_model(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).upper()
    return re.sub(r"[^A-Z0-9]+", "", value)


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[A-Z]+\d+[A-Z0-9-]*|[A-Z]{3,}|\d+[A-Z]+", value.upper())
        if len(token) >= 3
    }


def _request_json(url: str, payload: dict[str, Any], retries: int = 2) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "LifecyclePreview/1.0"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise AbbCollectionError(f"ABB 검색 API 요청 실패: {last_error}")


def _download(url: str, retries: int = 2) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "LifecyclePreview/1.0"})
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
    raise AbbCollectionError(f"PDF 다운로드 실패: {last_error}")


def _cached_notices(target: str) -> list[Notice] | None:
    entry = _NOTICE_CACHE.get(target)
    if entry is None:
        return None
    stored_at, notices = entry
    if time.monotonic() - stored_at >= NOTICE_CACHE_TTL_SECONDS:
        del _NOTICE_CACHE[target]
        return None
    return notices


def clear_notice_cache() -> None:
    """Drop cached search results (tests, or to force a fresh crawl)."""
    _NOTICE_CACHE.clear()


def _notice_from_document(document: dict[str, Any]) -> Notice:
    metadata = document["metadata"]
    identity = metadata["identification"]
    title = metadata["displayTitle"]["title"]
    language_codes = identity.get("languageCodes") or ["en"]
    return Notice(
        document_id=identity["documentNumber"],
        revision=identity.get("revision", ""),
        language=language_codes[0],
        title=title,
        published=(metadata.get("publishedDate") or "")[:10] or None,
        url=metadata.get("currentRevisionUrl") or metadata.get("latestRevisionUrl") or "",
        suffix=(metadata.get("fileSuffix") or "").lower(),
    )


def search_life_cycle_notices(
    target: str, use_cache: bool = True, budget: Deadline | None = None
) -> list[Notice]:
    """Read every ABB search result page, retaining titles containing life cycle.

    The result depends only on `target`, not on the model being looked up, yet a
    scheduled run asks for the same category once per registered model — 75 ABB
    Drive models meant 75 identical ~19-request crawls. Cached per target for
    NOTICE_CACHE_TTL_SECONDS so one run pays for it once while a long-lived web
    process still picks up newly published notices.
    """
    if use_cache:
        cached = _cached_notices(target)
        if cached is not None:
            return cached

    category_id = CATEGORY_IDS[target]
    notices: list[Notice] = []
    page_number = 1
    all_hits = None

    truncated = False
    while all_hits is None or (page_number - 1) * 50 < all_hits:
        if budget is not None and budget.expired():
            # 남은 페이지를 포기하고 지금까지 모은 공지로 진행한다. 미완성 목록을
            # 캐시에 넣으면 이후 모든 모델이 그 구멍을 물려받으므로 캐시는 건너뛴다.
            truncated = True
            break
        payload = {
            "Filters": [
                {"Criteria": 0, "Origin": 0, "Values": [category_id]},
                {"Criteria": 3, "Origin": 1, "Values": ["life cycle"]},
            ],
            "ResultsControl": {
                "PageNumber": page_number,
                "PageSize": 50,
                "Sort": [{"SortBy": "Score", "SortOrder": "Descending"}],
            },
            "Display": {"IncludeAllRevisions": False, "ResultsTranslationLanguage": "en"},
        }
        response = _request_json(SEARCH_URL, payload)
        all_hits = int(response.get("numberOfAllHits", 0))
        documents = response.get("documents", [])
        for document in documents:
            notice = _notice_from_document(document)
            if "life cycle" in notice.title.lower():
                notices.append(notice)
        if not documents:
            break
        page_number += 1
        time.sleep(0.15)

    if use_cache and not truncated:
        _NOTICE_CACHE[target] = (time.monotonic(), notices)
    return notices


def _relevance_score(model_name: str, text: str) -> int:
    normalized_model = normalize_model(model_name)
    normalized_text = normalize_model(text)
    if normalized_model and normalized_model in normalized_text:
        return 100
    model_tokens = _tokens(model_name)
    text_tokens = _tokens(text)
    shared = model_tokens & text_tokens
    if not shared:
        return 0
    return min(90, 25 * len(shared) + 5 * sum(len(token) >= 6 for token in shared))


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        raise AbbCollectionError("pypdf가 설치되어 있지 않아 PDF 텍스트를 분석할 수 없습니다.")
    import io

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _compact(text: str) -> str:
    return " ".join(text.replace("–", "-").replace("—", "-").split())


def _parse_date(value: str) -> date | None:
    value = value.strip()
    end = re.search(r"(?:the\s+)?end\s+of\s+(\d{4})", value, re.I)
    if end:
        return date(int(end.group(1)), 12, 31)
    iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if iso:
        return date(*map(int, iso.groups()))
    dmy = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value)
    if dmy:
        day, month, year = map(int, dmy.groups())
        return date(year, month, day)
    month_first = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s*(\d{4})", value)
    if month_first and month_first.group(1).lower() in MONTHS:
        month, day, year = month_first.groups()
        return date(int(year), MONTHS[month.lower()], int(day))
    day_first = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+)[,]?\s*(\d{4})", value)
    if day_first and day_first.group(2).lower() in MONTHS:
        day, month, year = day_first.groups()
        return date(int(year), MONTHS[month.lower()], int(day))
    return None


def _ko_date(value: date | None) -> str | None:
    return f"{value.year}년 {value.month}월 {value.day}일" if value else None


DATE_PATTERN = (
    r"(?:the\s+)?end\s+of\s+\d{4}|\d{4}-\d{1,2}-\d{1,2}|"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?[A-Za-z]+,?\s*\d{4}"
)


def _current_status(compact_text: str) -> tuple[str | None, date | None, str | None]:
    before_plan = re.split(r"life cycle plan", compact_text, maxsplit=1, flags=re.I)[0]
    pattern = (
        r"current life cycle status.{0,900}?\b(Active|Classic|Limited|Obsolete)\b"
        r".{0,220}?(?:since|on|starting from)\s+(" + DATE_PATTERN + r")"
    )
    match = re.search(pattern, before_plan, re.I)
    if match:
        return match.group(1).title(), _parse_date(match.group(2)), match.group(0).strip()
    match = re.search(
        r"current life cycle status.{0,900}?\b(Active|Classic|Limited|Obsolete)\b.{0,280}?\.",
        before_plan,
        re.I,
    )
    if match:
        return match.group(1).title(), None, match.group(0).strip()
    # Older ABB "phase change announcement" documents never say "current life
    # cycle status" at all — they only announce a transfer to a phase on a
    # date. If that date has already passed, the announced phase is the
    # current one; if it's still in the future, we don't know the prior
    # phase, so we deliberately don't guess.
    match = re.search(
        r"(?:will\s+be\s+)?transfer(?:red)?\s+to\s+(?:the\s+)?\b(Active|Classic|Limited|Obsolete)\b"
        r"\s+phase[^.]{0,160}?(?:on|by)\s+(" + DATE_PATTERN + r")[^.]*\.",
        before_plan,
        re.I,
    )
    if match:
        transition_date = _parse_date(match.group(2))
        if transition_date and transition_date <= date.today():
            return match.group(1).title(), transition_date, match.group(0).strip()
    return None, None, None


def _plan_section(compact_text: str) -> str:
    match = re.search(
        r"life cycle plan\s+(.{0,2500}?)(?=\s+(?:recommended actions|further information|document id)\b|$)",
        compact_text,
        re.I,
    )
    return match.group(1).strip() if match else ""


def _table_plan(section: str) -> tuple[str | None, date | None, str | None]:
    """Interpret common ABB table text such as 'From 01.04.2020 Obsolete'."""
    dmy = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
    starts: dict[str, date] = {}

    def add(state: str, raw_date: str) -> None:
        parsed = _parse_date(raw_date)
        if parsed and (state not in starts or parsed < starts[state]):
            starts[state] = parsed

    for match in re.finditer(rf"({dmy})\s*-\s*(?:(?:{dmy})\s*)?(Active|Classic|Limited|Obsolete)\b", section, re.I):
        add(match.group(2).title(), match.group(1))
    for match in re.finditer(rf"\bFrom\s+({dmy})\s+(Active|Classic|Limited|Obsolete)\b", section, re.I):
        add(match.group(2).title(), match.group(1))
    for match in re.finditer(rf"\b(Active|Classic|Limited|Obsolete)\s+({dmy})\s*(?:-|→|$)", section, re.I):
        add(match.group(1).title(), match.group(2))
    if not starts:
        return None, None, None

    today = date.today()
    applicable = [state for state, starts_on in starts.items() if starts_on <= today]
    if not applicable:
        return None, None, None
    current = max(applicable, key=lambda state: STATE_ORDER[state])
    target = starts[current] if current == "Obsolete" else starts.get(NEXT_STATE[current])
    return current, target, section


def _plan_transition(section: str, current: str) -> tuple[date | None, str | None, str | None]:
    """Return planned date, source sentence, and type: transition or phase_end."""
    if not section:
        return None, None, None
    next_state = NEXT_STATE.get(current)
    if next_state:
        patterns = [
            rf"[^.]*?\b{current}\b[^.]*?\buntil\s+(?:at\s+least\s+)?[^.]{{0,160}}?({DATE_PATTERN})[^.]*?"
            rf"(?:transfer(?:red)?|move[ds]?|change[ds]?)[^.]{{0,160}}?\b{next_state}\b[^.]*\.",
            rf"[^.]*?(?:transfer(?:red)?|move[ds]?|change[ds]?)[^.]{{0,180}}?\b{next_state}\b"
            rf"(?:\s+life\s+cycle)?\s+phase[^.]{{0,180}}?(?:(?:on|from|starting(?:\s+from)?)\s+)?({DATE_PATTERN})[^.]*\.",
            rf"[^.]*?(?:starting\s+from|from)\s+({DATE_PATTERN})[^.]*?\b{next_state}\b[^.]*?\bphase\b[^.]*?\b(?:will\s+)?start[^.]*\.",
        ]
        for pattern in patterns:
            match = re.search(pattern, section, re.I)
            if match:
                return _parse_date(match.group(1)), match.group(0).strip(), "transition"
        boundary = re.search(
            rf"[^.]*?\b(?:will\s+remain|planned\s+to\s+keep|will\s+be\s+kept)\b[^.]*?\b{current}\b"
            rf"[^.]*?\buntil\s+(?:at\s+least\s+)?({DATE_PATTERN})[^.]*\.",
            section,
            re.I,
        )
        if boundary:
            return _parse_date(boundary.group(1)), boundary.group(0).strip(), "phase_end"

    if current == "Obsolete":
        match = re.search(
            rf"[^.]*?(?:transfer(?:red)?|move[ds]?)[^.]{{0,300}}?\bObsolete\b[^.]{{0,300}}?"
            rf"(?:on|from)\s+({DATE_PATTERN})[^.]*\.",
            section,
            re.I,
        )
        if match:
            return _parse_date(match.group(1)), match.group(0).strip(), "transition"
    return None, None, None


def _model_from_text(model_name: str, current_sentence: str | None) -> str:
    """Use a PDF-specific subject only when it contains a recognisable model code."""
    if not current_sentence:
        return model_name
    match = re.search(
        r"(?:The|All)\s+(.+?)\s+(?:is|are)\s+(?:in|reaching)\s+(?:Active|Classic|Limited|Obsolete)\b",
        current_sentence,
        re.I,
    )
    if match:
        subject = match.group(1).strip(" ,")
        if re.search(r"\b(?:ACS|ACQ|ACH|ACV|DCS|PCS|CP|AC\d|TU\d|CM\d|PS\d|DC\d)", subject, re.I):
            return subject
    return model_name


def _stale_remark(published: str | None) -> str | None:
    if not published:
        return None
    try:
        published_date = date.fromisoformat(published)
    except ValueError:
        return None
    return "공지 10년 이상 경과, 공급사 문의 필요" if (date.today() - published_date).days >= 3652 else None


def _build_item(model_name: str, target: str, notice: Notice, pdf_text: str) -> tuple[dict[str, Any] | None, str]:
    compact_text = _compact(pdf_text)
    status, status_date, current_sentence = _current_status(compact_text)
    if not status:
        return None, "Current life cycle status 또는 단계 근거 없음"

    section = _plan_section(compact_text)
    table_state, table_date, table_source = _table_plan(section)
    plan_date: date | None = None
    plan_sentence: str | None = None
    plan_type: str | None = None

    if table_state:
        status = table_state
        plan_date, plan_sentence, plan_type = table_date, table_source, "table"
    else:
        plan_date, plan_sentence, plan_type = _plan_transition(section, status)
        if plan_type == "transition" and plan_date and plan_date <= date.today() and status in NEXT_STATE:
            status = NEXT_STATE[status]

    lifecycle_date = plan_date or status_date
    exact_model = _model_from_text(model_name, current_sentence)
    original_parts = [part for part in (current_sentence, plan_sentence) if part]
    original = " Life cycle plan ".join(original_parts)
    if not original:
        return None, "모델명·상태·날짜가 포함된 원문 근거 없음"

    evidence = f"공지 본문의 Current life cycle status 항목에서 {exact_model}의 현재 수명주기 상태가 {status}로 확인됩니다."
    if plan_type == "table" and lifecycle_date:
        evidence += f" Life cycle plan 표의 날짜별 단계 기준으로 적용일은 {_ko_date(lifecycle_date)}입니다."
    elif plan_type == "transition" and lifecycle_date:
        if status == "Obsolete":
            evidence += f" Life cycle plan 항목은 Obsolete 적용일을 {_ko_date(lifecycle_date)}로 명시합니다."
        else:
            evidence += f" Life cycle plan 항목은 다음 단계 전환일을 {_ko_date(lifecycle_date)}로 명시합니다."
    elif plan_type == "phase_end" and lifecycle_date:
        evidence += f" Life cycle plan 항목은 현재 상태의 유지 종료일을 {_ko_date(lifecycle_date)}로 명시합니다. 다음 단계명 미기재."
    elif status_date:
        evidence += f" 현재 상태 적용일은 {_ko_date(status_date)}입니다."
    else:
        evidence += " 공식 문서에 단계 적용일이 명시되지 않았습니다."

    return {
        "공급사": "ABB",
        "대상": target,
        "모델명": exact_model,
        "단종여부": STATE_LABEL[status],
        "단종시기": _ko_date(lifecycle_date),
        "적용_상태": status,
        "게시일": notice.published,
        "비고": _stale_remark(notice.published),
        "근거문장": evidence,
        "근거문장(원문)": original,
        "공지링크": notice.url,
    }, ""


def _model_codes(value: str) -> set[str]:
    """Product codes only — letters then digits: 'ACS880-104 R6i' -> {'ACS880'}."""
    return set(re.findall(r"[A-Z]{2,}\d{2,}[A-Z0-9]*", value.upper()))


def _spaced(value: str) -> str:
    """Normalize but keep token boundaries — 'ACS880-104' -> 'ACS880 104'."""
    return re.sub(r"[^A-Z0-9]+", " ", unicodedata.normalize("NFKD", value or "").upper())


def _code_present(code: str, text: str) -> bool:
    """Is this product code in the text as its own token?

    Boundaries matter: collapsing everything to letters and digits makes "ACS600"
    a substring of "ACS6000c", which is how an ACS6000c statement was accepted as
    ACS600 MultiDrive's status. Keeping separators as spaces lets "ACS880" still
    match "ACS880-104" while "ACS600" no longer matches "ACS6000c".
    """
    return re.search(rf"\b{re.escape(code)}\b", _spaced(text)) is not None


def _pdf_is_about_model(model_name: str, pdf_text: str) -> bool:
    """Does this document actually cover the requested model?

    Sharing any word used to be enough, and "Drives" appears in nearly every ABB
    life cycle PDF. So an "AF-6 Drives" lookup accepted the ACS800 liquid-cooled
    statement, and — because _model_from_text falls back to the queried name when
    it cannot read a subject — the result came back labelled "AF-6 Drives" with
    ACS800's dates. A wrong date wearing the right name is worse than no data, so
    the model's own product code (or its full name, when it has no code) has to
    appear in the document.
    """
    codes = _model_codes(model_name)
    if codes:
        return any(_code_present(code, pdf_text) for code in codes)
    return normalize_model(model_name) in normalize_model(pdf_text)


def _evidence_names_model(model_name: str, evidence: str | None, title: str) -> bool:
    """Is this notice really about the model, or does it just mention it in passing?

    A document can name a code incidentally ("replaces ACS600") while being about
    something else, so finding the code anywhere in the PDF is not enough — that is
    how ACS800's Classic phase got recorded as ACS600 MultiDrive's. Require the
    code in either the status evidence or the notice title, which is where ABB
    states what a document covers. Models with no parseable code (e.g. "AF-6
    Drives", whose notice speaks of AF-60/AF-600) keep the document-level check.
    """
    codes = _model_codes(model_name)
    if not codes:
        return True
    haystack = f"{evidence or ''} {title}"
    return any(_code_present(code, haystack) for code in codes)


def _subject_rank(model_name: str, subject: str) -> int:
    """How strongly a notice's subject is the model that was actually asked for.

    A shared English word ("Generation", "cooled") used to score as high as a
    shared product code, so an ACS6000 lookup could rank an ACS5000 notice first
    and the UI would show the wrong drive. A matching product code now outranks
    any amount of prose overlap.
    """
    query = normalize_model(model_name)
    candidate = normalize_model(subject)
    if query and candidate:
        if query == candidate:
            return 300
        if query in candidate or candidate in query:
            return 200
    query_codes = _model_codes(model_name)
    subject_codes = _model_codes(subject)
    if query_codes & subject_codes:
        return 100 + _relevance_score(model_name, subject)
    # 같은 계열의 변형(ACS6000 / ACS6000c)은 전혀 다른 계열보다는 관련이 있다.
    if any(a.startswith(b) or b.startswith(a) for a in query_codes for b in subject_codes):
        return 60 + _relevance_score(model_name, subject)
    return _relevance_score(model_name, subject)


def _deduplicate(items: Iterable[dict[str, Any]], model_name: str) -> list[dict[str, Any]]:
    """Collapse per subject, then order most-relevant-first so items[0] is the best match."""

    def date_key(item: dict[str, Any]) -> tuple[int, int, int]:
        match = re.fullmatch(r"(\d{4})년 (\d{1,2})월 (\d{1,2})일", item["단종시기"] or "")
        return tuple(map(int, match.groups())) if match else (0, 0, 0)

    output: dict[str, dict[str, Any]] = {}
    for item in items:
        key = normalize_model(item["모델명"])
        if key not in output or date_key(item) > date_key(output[key]):
            output[key] = item
    return sorted(
        output.values(),
        key=lambda item: (-_subject_rank(model_name, item["모델명"]), item["모델명"].upper()),
    )


def collect(model_name: str, target: str, deadline: Deadline | None = None) -> dict[str, Any]:
    """Collect ABB lifecycle preview items for one requested model.

    No DB action occurs here. Callers should display ``review`` and require
    a human registration decision before persisting returned ``items``.
    Work stops after ``deadline`` (default common.MODEL_DEADLINE_SECONDS).
    """
    target = target.strip().upper() if target.strip().upper() == "PLC" else target.strip().title()
    if target not in TARGETS:
        raise AbbCollectionError("target은 PLC, Drive, Motor 중 하나여야 합니다.")
    if not model_name or not model_name.strip():
        raise AbbCollectionError("model_name은 필수입니다.")
    if PdfReader is None:
        return {
            "items": [],
            "review": {"status": "error", "message": "pypdf 라이브러리가 필요합니다.", "candidates_checked": 0, "pdfs_checked": 0, "excluded": []},
        }

    budget = deadline or Deadline()
    notices = search_life_cycle_notices(target, budget=budget)
    scored = [(notice, _relevance_score(model_name, notice.title)) for notice in notices]
    relevant = [(notice, score) for notice, score in scored if score > 0]
    relevant.sort(key=lambda pair: pair[1], reverse=True)
    excluded: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []
    pdfs_checked = 0
    timed_out = False

    for notice, score in relevant[:20]:
        # 관련도 높은 순으로 보므로, 시간이 다하면 남은 저관련 후보를 버려도
        # 가장 중요한 근거는 이미 확보한 상태다.
        if budget.expired():
            timed_out = True
            excluded.append({"title": notice.title, "reason": f"모델당 수집 시간 상한({budget.seconds:.0f}초) 초과로 미확인"})
            continue
        if notice.suffix != "pdf" or not notice.url:
            excluded.append({"title": notice.title, "reason": "PDF 없음"})
            continue
        try:
            pdf_text = _extract_pdf_text(_download(notice.url))
            pdfs_checked += 1
        except AbbCollectionError as error:
            excluded.append({"title": notice.title, "reason": str(error)})
            continue
        if not _pdf_is_about_model(model_name, pdf_text):
            excluded.append({"title": notice.title, "reason": "PDF 본문이 이 모델을 다루지 않음"})
            continue
        item, reason = _build_item(model_name, target, notice, pdf_text)
        if item and not _evidence_names_model(model_name, item["근거문장(원문)"], notice.title):
            item, reason = None, "상태 근거 문장이 다른 제품을 가리킴"
        if item:
            items.append(item)
        else:
            excluded.append({"title": notice.title, "reason": reason})
        time.sleep(0.15)

    items = _deduplicate(items, model_name)
    if items:
        status = "ready" if all(item["단종시기"] is not None for item in items) else "review_required"
        message = "공식 ABB 문서 기반 미리보기 데이터를 생성했습니다."
        if status == "review_required":
            message = "상태는 확인됐지만 일부 항목의 공식 단종시기가 없습니다. 등록 전 검토가 필요합니다."
    elif relevant:
        status = "review_required"
        message = "관련 공지는 찾았지만 DB 등록에 필요한 수명주기 근거를 확인하지 못했습니다."
    else:
        status = "not_found"
        message = "선택한 ABB 카테고리의 life cycle 공지에서 입력 모델과 일치하는 결과를 찾지 못했습니다."
    if timed_out:
        status = "review_required"
        message += f" (모델당 수집 시간 상한 {budget.seconds:.0f}초를 넘겨 일부 공지를 확인하지 못했습니다.)"
    return {
        "items": items,
        "review": {
            "status": status,
            "message": message,
            "timed_out": timed_out,
            "candidates_checked": len(notices),
            "pdfs_checked": pdfs_checked,
            "excluded": excluded,
        },
    }

