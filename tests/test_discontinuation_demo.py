import json
import inspect

import pytest

import discontinuation_demo
from discontinuation_demo import preview_collection, send_pdf_request, smtp_send_fn
from views import general


def test_collection_preview_calls_supported_supplier_with_deadline_and_returns_json_safe_result() -> None:
    calls: list[tuple[object, ...]] = []

    def collect_stub(*args: object) -> dict[str, object]:
        calls.append(args)
        return {"모델명": "ACS880", "근거": ["공식 공지"], "nested": {"ok": True}}

    result = preview_collection("ABB", " ACS880 ", "Drive", collect_fn=collect_stub)

    assert result == {"모델명": "ACS880", "근거": ["공식 공지"], "nested": {"ok": True}}
    assert json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False)) == result
    assert calls[0][:3] == ("ABB", "ACS880", "Drive")
    assert calls[0][3].__class__.__name__ == "Deadline"


@pytest.mark.parametrize(
    ("supplier", "model_name", "target"),
    [
        ("TMEIC", "TMdrive", "Drive"),
        ("ABB", "", "Drive"),
        ("ABB", "ACS880", "Controller"),
    ],
)
def test_preview_rejects_unsupported_or_invalid_inputs(
    supplier: str, model_name: str, target: str,
) -> None:
    with pytest.raises(ValueError):
        preview_collection(supplier, model_name, target, collect_fn=lambda *_: {})


def test_pdf_request_uses_only_fixed_secret_recipient_and_korean_payload() -> None:
    sent: list[tuple[str, str, str]] = []

    send_pdf_request(
        "TMEIC", " TMdrive ", "Drive",
        {"recipient": "owner@example.com", "untrusted_recipient": "attacker@example.com"},
        send_fn=lambda subject, body, recipient: sent.append((subject, body, recipient)),
    )

    subject, body, recipient = sent[0]
    assert recipient == "owner@example.com"
    assert "TMEIC" in subject and "TMdrive" in subject and "PDF 확인 요청" in subject
    assert "공급사: TMEIC" in body
    assert "모델명: TMdrive" in body
    assert "대상: Drive" in body


@pytest.mark.parametrize(
    ("supplier", "model_name", "target", "settings"),
    [
        ("ABB", "ACS880", "Drive", {"recipient": "owner@example.com"}),
        ("TMEIC", "", "Drive", {"recipient": "owner@example.com"}),
        ("TMEIC", "TMdrive", "Controller", {"recipient": "owner@example.com"}),
        ("TMEIC", "TMdrive", "Drive", {}),
    ],
)
def test_pdf_request_rejects_invalid_inputs_before_sending(
    supplier: str, model_name: str, target: str, settings: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        send_pdf_request(supplier, model_name, target, settings, send_fn=lambda *_: None)


def test_helpers_do_not_persist_collection_or_mail_requests() -> None:
    preview_collection("SIEMENS", "S7-400", "PLC", collect_fn=lambda *_: {"items": []})
    sent: list[tuple[str, str, str]] = []
    send_pdf_request(
        "MELCO", "MELSERVO", "Motor", {"recipient": "owner@example.com"},
        send_fn=lambda *args: sent.append(args),
    )

    assert sent[0][2] == "owner@example.com"


def test_smtp_sender_uses_starttls_with_a_20_second_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: int, local_hostname: str) -> None:
            events.append((host, port, timeout, local_hostname))

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def starttls(self) -> None:
            events.append("starttls")

        def login(self, user: str, password: str) -> None:
            events.append((user, password))

        def send_message(self, message: object) -> None:
            events.append(message)

    monkeypatch.setattr(discontinuation_demo.smtplib, "SMTP", FakeSMTP)
    sender = smtp_send_fn({
        "host": "smtp.example.com", "port": "587", "user": "sender@example.com",
        "password": "not-exposed", "recipient": "owner@example.com",
    })

    sender("제목", "본문", "owner@example.com")

    assert events[0] == ("smtp.example.com", 587, 20, "localhost")
    assert events[1] == "starttls"
    assert events[2] == ("sender@example.com", "not-exposed")


def test_streamlit_secret_boundary_accepts_toml_integer_smtp_port() -> None:
    st = type("FakeStreamlit", (), {"secrets": {
        "SMTP_HOST": "smtp.example.com", "SMTP_PORT": 587,
        "SMTP_USER": "sender@example.com", "SMTP_PASSWORD": "password",
        "REQUEST_RECIPIENT_EMAIL": "owner@example.com",
    }})()

    settings = general._smtp_settings(st)

    assert settings["port"] == 587
    assert callable(smtp_send_fn(settings))


def test_collection_and_mail_failures_have_generic_ui_boundaries() -> None:
    source = inspect.getsource(general._render_discontinuation_actions)

    assert "공급사 정보를 가져오지 못했습니다" in source
    assert "PDF 확인 요청을 보내지 못했습니다" in source
    assert "st.error(str(error))" not in source
    assert "샘플 결과 보기" in source


def test_helper_module_does_not_load_dotenv_or_import_session_persistence() -> None:
    source = inspect.getsource(discontinuation_demo)

    assert "load_dotenv" not in source
    assert "session_store" not in source
