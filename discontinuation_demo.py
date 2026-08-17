"""Non-persistent supplier collection previews and fixed-recipient PDF requests."""

from __future__ import annotations

import json
import smtplib
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from typing import Any

from lifecycle.collectors import collect
from lifecycle.collectors.common import Deadline


WEB_PREVIEW_SUPPLIERS = frozenset({"ABB", "SIEMENS", "HITACHI"})
PDF_REQUEST_SUPPLIERS = frozenset({"TMEIC", "TOSHIBA", "MELCO"})
TARGETS = frozenset({"PLC", "Drive", "Motor"})


def _validated_values(
    supplier: object, model_name: object, target: object, allowed_suppliers: frozenset[str],
) -> tuple[str, str, str]:
    """Validate form values before any external collector or SMTP call."""

    if not isinstance(supplier, str) or supplier not in allowed_suppliers:
        raise ValueError("지원하지 않는 공급사입니다.")
    if not isinstance(model_name, str) or not (safe_model_name := model_name.strip()):
        raise ValueError("모델명을 입력하세요.")
    if not isinstance(target, str) or target not in TARGETS:
        raise ValueError("지원하지 않는 대상입니다.")
    return supplier, safe_model_name, target


def _json_safe_preview(value: object) -> dict[str, Any]:
    """Return an independent JSON-only preview suitable for ``st.json``."""

    if not isinstance(value, Mapping):
        raise ValueError("수집 결과 형식이 올바르지 않습니다.")
    try:
        preview = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError("수집 결과를 미리보기로 표시할 수 없습니다.") from error
    if not isinstance(preview, dict):
        raise ValueError("수집 결과 형식이 올바르지 않습니다.")
    return preview


def preview_collection(
    supplier: str, model_name: str, target: str, collect_fn: Callable[..., object] = collect,
) -> dict[str, Any]:
    """Collect one supported supplier result for display without storing it."""

    safe_supplier, safe_model_name, safe_target = _validated_values(
        supplier, model_name, target, WEB_PREVIEW_SUPPLIERS,
    )
    result = collect_fn(safe_supplier, safe_model_name, safe_target, Deadline())
    return _json_safe_preview(result)


def _recipient(smtp_settings: Mapping[str, object]) -> str:
    """Read the one caller-independent recipient from prevalidated settings."""

    try:
        recipient = smtp_settings["recipient"]
    except KeyError as error:
        raise ValueError("이메일 발송 설정이 올바르지 않습니다.") from error
    if not isinstance(recipient, str) or not recipient.strip():
        raise ValueError("이메일 발송 설정이 올바르지 않습니다.")
    return recipient.strip()


def send_pdf_request(
    supplier: str,
    model_name: str,
    target: str,
    smtp_settings: Mapping[str, object],
    send_fn: Callable[[str, str, str], None],
) -> None:
    """Send a Korean PDF request only to ``smtp_settings['recipient']``."""

    safe_supplier, safe_model_name, safe_target = _validated_values(
        supplier, model_name, target, PDF_REQUEST_SUPPLIERS,
    )
    recipient = _recipient(smtp_settings)
    subject = f"[단종 정보 수집] {safe_supplier} {safe_model_name} PDF 확인 요청"
    body = (
        f"공급사: {safe_supplier}\n"
        f"모델명: {safe_model_name}\n"
        f"대상: {safe_target}\n\n"
        "위 모델의 공식 단종 공지 PDF를 확인해 주시고, 확인되면 시연 앱에 등록해 주세요."
    )
    send_fn(subject, body, recipient)


def smtp_send_fn(smtp_settings: Mapping[str, object]) -> Callable[[str, str, str], None]:
    """Create the real SMTP sender from Streamlit-secret values supplied by the UI."""

    host = smtp_settings.get("host")
    port_raw = smtp_settings.get("port")
    user = smtp_settings.get("user")
    password = smtp_settings.get("password")
    if not all(isinstance(value, str) and value.strip() for value in (host, user, password)):
        raise ValueError("이메일 발송 설정이 올바르지 않습니다.")
    try:
        port = int(port_raw)  # Streamlit secrets may provide the port as text or an integer.
    except (TypeError, ValueError) as error:
        raise ValueError("이메일 발송 설정이 올바르지 않습니다.") from error
    if not 1 <= port <= 65535:
        raise ValueError("이메일 발송 설정이 올바르지 않습니다.")

    safe_host = host.strip()
    safe_user = user.strip()
    safe_password = password.strip()

    def send(subject: str, body: str, recipient: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = safe_user
        message["To"] = recipient
        message.set_content(body)
        with smtplib.SMTP(safe_host, port, timeout=20, local_hostname="localhost") as server:
            server.starttls()
            server.login(safe_user, safe_password)
            server.send_message(message)

    return send
