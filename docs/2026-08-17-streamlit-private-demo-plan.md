# Streamlit 비공개 시연 앱 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or inline execution task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비공개 초대 사용자가 전체 EIC 타당성 검토와 단종 관리 흐름을 세션 단위로 시연하고, Secrets 기반 관리자가 관리자 기능을 사용할 수 있는 Streamlit 앱을 `SL/`에 구축한다.

**Architecture:** `SL/`은 기존 FastAPI 서버와 독립된 Streamlit 앱이다. 순수 데이터·권한·세션 저장소 계층이 UI와 분리되고, 기존 `lifecycle`의 문서 파서·AI 클라이언트·수집기·SMTP 헬퍼를 재사용한다. 모든 프로젝트·사용자·검토·이력 변경은 `st.session_state`에만 저장하며, 파일은 현재 세션의 임시 디렉터리에서만 사용한다.

**Tech Stack:** Python 3.11+, Streamlit, pytest, pypdf, PyMuPDF, python-pptx, openpyxl, PyYAML, stdlib urllib/smtplib, 기존 `lifecycle` 모듈.

## Global Constraints

- 모든 새 코드, 테스트, 문서, 배포 설정은 `SL/` 아래에만 둔다.
- Community Cloud 앱은 `Only specific people can view this app`으로 배포한다.
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `TAVILY_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `REQUEST_RECIPIENT_EMAIL`은 Cloud Secrets에서만 읽는다.
- `.env`, `data/`, 운영 SQLite DB, 운영 업로드 파일을 읽거나 수정하지 않는다.
- API 키·SMTP 비밀번호·관리자 비밀번호를 화면, 로그, 테스트 실패 메시지, URL, 캐시에 기록하지 않는다.
- 일반 사용자는 관리자 페이지와 관리자 변경 동작을 사용할 수 없고, 모든 관리자 동작은 서버 측 역할 검사로 보호한다.
- 세션 변경은 새 세션 또는 앱 재시작 시 초기 데모 데이터로 복구됨을 UI에 고지한다.
- 공급사 웹 수집은 결과 미리보기만 제공하며 DB에 자동 등록하지 않는다. PDF 확인 요청은 고정 수신자에게 SMTP로 실제 발송하고 DB에는 기록하지 않는다.

---

## File Structure

- `SL/streamlit_app.py` — 페이지 설정, Secrets 검증, 역할별 라우팅과 공통 네비게이션
- `SL/auth.py` — `Role`, 관리자 자격 증명 검증, 관리자 전용 접근 차단
- `SL/models.py` — 프로젝트·설비·사용자·검토·이력·챗 메시지의 dataclass와 직렬화 함수
- `SL/demo_data.py` — 초기 시연 데이터 생성
- `SL/session_store.py` — 세션 상태 초기화 및 모든 CRUD·상태 전이
- `SL/storage.py` — 세션 임시 디렉터리의 업로드 저장·삭제·파일명 안전화
- `SL/ai_demo.py` — 기존 AI 클라이언트 조합, 문서 파싱, 식별·평가·재검토·챗봇
- `SL/discontinuation_demo.py` — 공급사 수집 미리보기와 고정 수신자 SMTP 요청
- `SL/pages/landing.py` — 초대 사용자/관리자 선택과 관리자 로그인
- `SL/pages/general.py` — 타당성 검토 프로젝트, 업로드, 설비, 분석, 보고서, 이력
- `SL/pages/admin.py` — 사용자·로그·통계·단종 검토·장비 목록 관리자 화면
- `SL/tests/` — 위 순수 계층과 Streamlit UI 경계의 pytest 검증
- `SL/requirements.txt`, `SL/.streamlit/config.toml`, `SL/.gitignore`, `SL/README.md` — 독립 배포 구성

### Task 1: 독립 실행·배포 골격 만들기

**Files:**
- Create: `SL/requirements.txt`
- Create: `SL/.streamlit/config.toml`
- Create: `SL/.gitignore`
- Create: `SL/streamlit_app.py`
- Create: `SL/tests/test_app_bootstrap.py`
- Create: `SL/README.md`

**Interfaces:**
- Produces: `main() -> None`, `required_secret_names() -> tuple[str, ...]`
- Consumes: no new modules; imports are intentionally delayed until the app boots.

- [ ] **Step 1: Write the failing bootstrap test**

```python
from streamlit_app import required_secret_names


def test_required_secret_names_cover_admin_ai_and_smtp() -> None:
    assert set(required_secret_names()) == {
        "ADMIN_USERNAME", "ADMIN_PASSWORD", "OPENAI_API_KEY", "OPENAI_MODEL",
        "TAVILY_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "REQUEST_RECIPIENT_EMAIL",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd SL && pytest tests/test_app_bootstrap.py -v`

Expected: FAIL because `streamlit_app` does not exist.

- [ ] **Step 3: Create the minimal deployable app and configuration**

Create `requirements.txt` with `streamlit`, `pytest`, and the same parser/network packages pinned compatibly with the root project. Add a local `config.toml` that disables usage statistics and raises upload capacity only to the chosen demo limit. Add `.gitignore` entries for `.streamlit/secrets.toml`, `.env`, `.pytest_cache/`, `__pycache__/`, and temporary uploads. Implement:

```python
def required_secret_names() -> tuple[str, ...]:
    return (
        "ADMIN_USERNAME", "ADMIN_PASSWORD", "OPENAI_API_KEY", "OPENAI_MODEL",
        "TAVILY_API_KEY", "SMTP_HOST", "SMTP_PORT", "SMTP_USER",
        "SMTP_PASSWORD", "REQUEST_RECIPIENT_EMAIL",
    )


def main() -> None:
    import streamlit as st
    st.set_page_config(page_title="EIC 교체 타당성 검토 데모", layout="wide")
    st.caption("시연 데이터는 현재 브라우저 세션에만 저장됩니다.")
```

Document local launch, Cloud Secrets names without values, private-sharing configuration, and the fact that Cloud Secrets must be entered in TOML format.

- [ ] **Step 4: Run the bootstrap test and start the app**

Run: `cd SL && pytest tests/test_app_bootstrap.py -v && streamlit run streamlit_app.py --server.headless true`

Expected: test PASS and Streamlit starts without importing production `.env` or `data/`.

- [ ] **Step 5: Commit**

```bash
git add SL/requirements.txt SL/.streamlit/config.toml SL/.gitignore SL/streamlit_app.py SL/tests/test_app_bootstrap.py SL/README.md
git commit -m "feat: scaffold private Streamlit demo"
```

### Task 2: 세션 도메인 모델과 데모 저장소 구현

**Files:**
- Create: `SL/models.py`
- Create: `SL/demo_data.py`
- Create: `SL/session_store.py`
- Create: `SL/tests/test_session_store.py`

**Interfaces:**
- Produces: `initialize_state(state: MutableMapping[str, object]) -> None`, `create_project(state, payload) -> str`, `update_project(state, project_id, payload) -> None`, `transition_project(state, project_id, status) -> None`, `create_report_version(state, project_id, reason) -> str`, `approve_user(state, user_id) -> None`, `decide_review(state, review_id, decision) -> None`.
- Consumes: standard-library dataclasses only; later UI and AI tasks use these functions rather than directly assigning store collections.

- [ ] **Step 1: Write failing session-store tests**

```python
from session_store import create_project, initialize_state, transition_project


def test_project_status_change_is_visible_only_in_current_state() -> None:
    first, second = {}, {}
    initialize_state(first)
    initialize_state(second)
    project_id = create_project(first, {"investment_code": "DEMO-1", "project_name": "테스트"})
    transition_project(first, project_id, "confirmed")
    assert first["projects"][project_id]["status"] == "confirmed"
    assert all(row["status"] != "confirmed" for row in second["projects"].values())
```

```python
from session_store import create_report_version, initialize_state


def test_re_review_creates_immutable_report_snapshot() -> None:
    state = {}
    initialize_state(state)
    project_id = next(iter(state["projects"]))
    version_id = create_report_version(state, project_id, "조건 변경")
    assert state["report_versions"][version_id]["project_id"] == project_id
    assert state["report_versions"][version_id]["reason"] == "조건 변경"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_session_store.py -v`

Expected: FAIL because `session_store` is missing.

- [ ] **Step 3: Implement typed models, seed data, and CRUD boundaries**

Use UUID strings for IDs and JSON-serializable dictionaries at the `st.session_state` boundary. Seed approved/pending/rejected users, reviewed/pending lifecycle records, one complete project, per-equipment reports, and activity/login log entries. Restrict project states to `draft`, `reviewed`, `confirmed`, and `on_hold`; reject invalid transitions with `ValueError`. Implement deletion, equipment insert/update/delete, document metadata association, activity log creation, user decisions, lifecycle decisions, and report snapshots through named store functions.

- [ ] **Step 4: Run focused tests**

Run: `cd SL && pytest tests/test_session_store.py -v`

Expected: PASS; a fresh state has seed data and never observes another state mapping's changes.

- [ ] **Step 5: Commit**

```bash
git add SL/models.py SL/demo_data.py SL/session_store.py SL/tests/test_session_store.py
git commit -m "feat: add session-backed demo state"
```

### Task 3: 역할 선택과 관리자 접근 제어 구현

**Files:**
- Create: `SL/auth.py`
- Create: `SL/pages/__init__.py`
- Create: `SL/pages/landing.py`
- Modify: `SL/streamlit_app.py`
- Create: `SL/tests/test_auth.py`

**Interfaces:**
- Consumes: `initialize_state(state)` from `session_store.py`.
- Produces: `Role = Literal["guest", "admin"]`, `authenticate_admin(username, password, secrets) -> bool`, `enter_guest(state) -> None`, `enter_admin(state) -> None`, `require_admin(state) -> bool`.

- [ ] **Step 1: Write failing authorization tests**

```python
from auth import authenticate_admin, require_admin


def test_admin_authentication_requires_both_secret_values() -> None:
    secrets = {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "correct"}
    assert authenticate_admin("admin", "correct", secrets) is True
    assert authenticate_admin("admin", "wrong", secrets) is False


def test_guest_cannot_pass_admin_guard() -> None:
    assert require_admin({"role": "guest"}) is False
    assert require_admin({"role": "admin"}) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_auth.py -v`

Expected: FAIL because `auth` is missing.

- [ ] **Step 3: Implement landing and guarded routing**

Use `hmac.compare_digest` for both username and password checks. The landing page must show exactly two choices: `초대 사용자` sets the `guest` role and opens general navigation; `관리자` opens a login form. On failed login show only `관리자 인증에 실패했습니다.` Do not use query parameters or plaintext status messages for credentials. Every admin navigation branch must call `require_admin`; on failure show an access-denied notice and route to landing. Include a logout action that clears role and removes any password widget key from session state.

- [ ] **Step 4: Run focused tests and manual guard check**

Run: `cd SL && pytest tests/test_auth.py -v`

Expected: PASS. In a manual Streamlit run, choosing `초대 사용자` never renders the admin page, and incorrect credentials expose neither required key name nor secret content.

- [ ] **Step 5: Commit**

```bash
git add SL/auth.py SL/pages/__init__.py SL/pages/landing.py SL/streamlit_app.py SL/tests/test_auth.py
git commit -m "feat: add guest and admin demo access"
```

### Task 4: 세션 파일 관리와 일반 사용자 프로젝트 흐름 구현

**Files:**
- Create: `SL/storage.py`
- Create: `SL/pages/general.py`
- Create: `SL/tests/test_storage.py`
- Create: `SL/tests/test_general_workflow.py`
- Modify: `SL/session_store.py`
- Modify: `SL/streamlit_app.py`

**Interfaces:**
- Consumes: `create_project`, equipment CRUD, `initialize_state` from `session_store.py`.
- Produces: `save_uploads(files, session_token, root: Path) -> list[StoredUpload]`, `cleanup_session_files(session_token, root: Path) -> None`, `render_general_page() -> None`.

- [ ] **Step 1: Write failing storage and workflow tests**

```python
from io import BytesIO
from pathlib import Path
from storage import save_uploads


class Upload:
    name = "../../unsafe.PDF"
    def getbuffer(self):
        return BytesIO(b"%PDF-1.4").getbuffer()


def test_upload_is_saved_under_its_session_directory(tmp_path: Path) -> None:
    stored = save_uploads([Upload()], "session-a", tmp_path)
    assert stored[0].path.parent == tmp_path / "session-a"
    assert stored[0].path.name == "unsafe.PDF"
```

```python
def test_project_workflow_creates_equipment_and_report_version(state) -> None:
    project_id = state["project_id"]
    # Use the store's public equipment and snapshot functions, not direct mutation.
    assert project_id in state["projects"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_storage.py tests/test_general_workflow.py -v`

Expected: FAIL because `storage` and workflow helpers are missing.

- [ ] **Step 3: Implement safe session-only files and the non-AI pages**

Accept only `.pdf`, `.pptx`, `.xlsx`; normalize filenames with `Path(name).name`; reject zero-byte files, per-file files above 20 MiB, and combined uploads above 40 MiB. Use `tempfile.gettempdir()/"eic-sl-demo"/<session-token>` and never `data/`. Implement the project list, create/edit form, status transitions, project delete, manual equipment CRUD, document list/download/preview entry points, report view, confirm/hold/resume, and report-history pages. Every state-changing UI action must call the store API and append an activity log.

- [ ] **Step 4: Run workflow tests**

Run: `cd SL && pytest tests/test_storage.py tests/test_general_workflow.py -v`

Expected: PASS; traversal names cannot leave the session directory and a guest workflow can create/edit/delete only session data.

- [ ] **Step 5: Commit**

```bash
git add SL/storage.py SL/pages/general.py SL/session_store.py SL/streamlit_app.py SL/tests/test_storage.py SL/tests/test_general_workflow.py
git commit -m "feat: add session-only feasibility workflow"
```

### Task 5: 실제 AI 평가·재검토·챗봇 통합

**Files:**
- Create: `SL/ai_demo.py`
- Create: `SL/tests/test_ai_demo.py`
- Modify: `SL/pages/general.py`
- Modify: `SL/session_store.py`

**Interfaces:**
- Consumes: `parse_uploaded_files` from `lifecycle.extraction.pipeline`, `OpenAIExtractionClient`, `FactorExtractionClient`, `TechnicalOpinionClient`, `RiskChecklistClient`, `NewModelReviewClient`, `ChatbotClient`, `build_project_context`, criteria/scoring modules, and store equipment/report APIs.
- Produces: `analyze_project(state, project_id, api_key, model, tavily_api_key) -> AnalysisOutcome`, `re_review_project(state, project_id, reason, api_key, model, tavily_api_key) -> AnalysisOutcome`, `answer_equipment_chat(state, project_id, equipment_id, question, api_key, model, tavily_api_key) -> ChatOutcome`.

- [ ] **Step 1: Write failing AI orchestration tests with injected clients**

```python
from ai_demo import analyze_project


def test_analysis_persists_identified_equipment_only_in_given_state(fake_state, fake_clients) -> None:
    outcome = analyze_project(fake_state, "project-1", clients=fake_clients)
    assert outcome.failed == []
    assert len(fake_state["equipment"]["project-1"]) == 1
    assert fake_state["equipment"]["project-1"][0]["technical_opinion"] == "교체 검토 의견"
```

```python
from ai_demo import answer_equipment_chat


def test_chat_history_is_scoped_to_one_equipment(fake_state, fake_clients) -> None:
    answer_equipment_chat(fake_state, "project-1", "equipment-a", "질문", clients=fake_clients)
    assert len(fake_state["chat_messages"][("project-1", "equipment-a")]) == 2
    assert ("project-1", "equipment-b") not in fake_state["chat_messages"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_ai_demo.py -v`

Expected: FAIL because `ai_demo` is missing.

- [ ] **Step 3: Implement an in-memory assessment adapter**

Parse only paths returned by `save_uploads`. Use `OpenAIExtractionClient.identify_equipment`, then use the existing criteria loader, factor client, scoring function, technical-opinion client, new-model-review client, and risk-checklist client without calling the SQLite-persisting `assess_batch`. Transform each result into the session-store equipment schema. Save each detailed result, sources, and immutable report snapshot through store APIs. Create a report UI that shows factors, technical opinion, risk checklist, new-model review, and one chat transcript per `(project_id, equipment_id)`. Route external-information questions through `ChatbotClient` and show returned source links. Require a nonempty OpenAI key for AI actions; make Tavily optional so the chatbot still answers from project context if it is absent. Use a fixed per-session counter for AI actions and block after the documented cap without exposing secret values.

- [ ] **Step 4: Run focused tests**

Run: `cd SL && pytest tests/test_ai_demo.py -v`

Expected: PASS with fake clients; no test uses a live API key.

- [ ] **Step 5: Commit**

```bash
git add SL/ai_demo.py SL/pages/general.py SL/session_store.py SL/tests/test_ai_demo.py
git commit -m "feat: add live AI assessment demo"
```

### Task 6: 관리자 시연 기능 구현

**Files:**
- Create: `SL/pages/admin.py`
- Create: `SL/tests/test_admin.py`
- Modify: `SL/session_store.py`
- Modify: `SL/streamlit_app.py`

**Interfaces:**
- Consumes: `require_admin(state)` from `auth.py`; approval, review-decision, activity-log, and export functions from `session_store.py`.
- Produces: `render_admin_page() -> None`, `export_approved_equipment(state) -> bytes`.

- [ ] **Step 1: Write failing admin-state tests**

```python
from session_store import approve_user, export_approved_equipment, initialize_state


def test_admin_user_approval_updates_session_and_activity_log() -> None:
    state = {}
    initialize_state(state)
    user_id = next(row["id"] for row in state["users"].values() if row["status"] == "pending")
    approve_user(state, user_id)
    assert state["users"][user_id]["status"] == "approved"
    assert state["activity_logs"][-1]["action_type"] == "approve_user"


def test_approved_equipment_export_is_json_bytes() -> None:
    state = {}
    initialize_state(state)
    assert export_approved_equipment(state).startswith(b"[")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_admin.py -v`

Expected: FAIL because the new export and admin renderer do not exist.

- [ ] **Step 3: Implement administrator pages and actions**

At the top of `render_admin_page`, enforce `require_admin`; otherwise call `st.stop()` after access denial. Render user approval/rejection, login log, activity log, project/user stats, lifecycle review queue, individual/bulk approval/rejection, approved equipment list, and `st.download_button` JSON export. Seeded data and current session changes must drive every table/chart. Append activity logs for every decision. Do not render SMTP credentials, API keys, password fields, or raw exceptions in any table or download.

- [ ] **Step 4: Run focused tests and manual guard check**

Run: `cd SL && pytest tests/test_admin.py tests/test_auth.py -v`

Expected: PASS. In a browser, a guest cannot reach any admin operation and an admin sees all management sections.

- [ ] **Step 5: Commit**

```bash
git add SL/pages/admin.py SL/session_store.py SL/streamlit_app.py SL/tests/test_admin.py
git commit -m "feat: add session-backed admin demo"
```

### Task 7: 단종 수집 미리보기와 실제 PDF 확인 요청 이메일 구현

**Files:**
- Create: `SL/discontinuation_demo.py`
- Create: `SL/tests/test_discontinuation_demo.py`
- Modify: `SL/pages/general.py`
- Modify: `SL/pages/admin.py`

**Interfaces:**
- Consumes: `collect` from `lifecycle.collectors`, `Deadline` from `lifecycle.collectors.common`, and SMTP settings passed explicitly from Cloud Secrets.
- Produces: `preview_collection(supplier, model_name, target, collect_fn=collect) -> dict`, `send_pdf_request(supplier, model_name, target, smtp_settings, send_fn) -> None`.

- [ ] **Step 1: Write failing collection and email tests**

```python
from discontinuation_demo import preview_collection, send_pdf_request


def test_collection_preview_calls_supported_supplier_without_persisting() -> None:
    result = preview_collection("ABB", "ACS880", "Drive", collect_fn=lambda *args: {"모델명": "ACS880"})
    assert result["모델명"] == "ACS880"


def test_pdf_request_uses_only_secret_recipient() -> None:
    sent = []
    send_pdf_request(
        "TMEIC", "TMdrive", "Drive",
        {"recipient": "owner@example.com"},
        send_fn=lambda subject, body, recipient: sent.append((subject, body, recipient)),
    )
    assert sent[0][2] == "owner@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SL && pytest tests/test_discontinuation_demo.py -v`

Expected: FAIL because `discontinuation_demo` is missing.

- [ ] **Step 3: Implement non-persistent collector and SMTP boundary**

Allow only `ABB`, `SIEMENS`, `HITACHI` for collector preview and apply a wall-clock `Deadline`; render returned evidence as a preview and never call review-queue store methods automatically. Allow only `TMEIC`, `TOSHIBA`, `MELCO` for PDF requests. Build the email subject/body from form values but obtain the recipient exclusively from `REQUEST_RECIPIENT_EMAIL`. Implement a local `send_fn` wrapper with `smtplib.SMTP`, STARTTLS, a 20-second timeout, and credentials read only from `st.secrets`; do not reuse code that loads `.env`. Show a generic success/failure notice, append a session activity log, and never include server errors in the UI.

- [ ] **Step 4: Run focused tests**

Run: `cd SL && pytest tests/test_discontinuation_demo.py -v`

Expected: PASS; tests mock collection and SMTP and no email is sent.

- [ ] **Step 5: Commit**

```bash
git add SL/discontinuation_demo.py SL/pages/general.py SL/pages/admin.py SL/tests/test_discontinuation_demo.py
git commit -m "feat: add live collection preview and PDF request email"
```

### Task 8: 보안 회귀, UI 경계, 배포 검증

**Files:**
- Create: `SL/tests/test_security_regressions.py`
- Modify: `SL/README.md`
- Modify: `SL/streamlit_app.py`
- Modify: `SL/pages/general.py`
- Modify: `SL/pages/admin.py`

**Interfaces:**
- Consumes: all public functions from Tasks 1–7.
- Produces: a documented Cloud deployment checklist and a complete passing test suite.

- [ ] **Step 1: Write failing security-regression tests**

```python
from auth import authenticate_admin


def test_error_paths_never_interpolate_secret_values() -> None:
    secrets = {"ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "secret-password"}
    assert authenticate_admin("admin", "bad", secrets) is False
    # Authentication returns only a boolean, so callers cannot accidentally render a secret.
```

```python
from pathlib import Path


def test_sl_sources_do_not_load_root_dotenv_or_data_db() -> None:
    source = "\n".join(path.read_text() for path in Path(".").rglob("*.py") if "tests" not in path.parts)
    assert "load_dotenv" not in source
    assert "data/lifecycle.db" not in source
```

- [ ] **Step 2: Run tests to verify the final checks fail or expose violations**

Run: `cd SL && pytest tests/test_security_regressions.py -v`

Expected: initially FAIL until no app code imports root dotenv or production DB paths.

- [ ] **Step 3: Implement final UX and deployment safeguards**

Add a persistent session-only warning, separate admin-only navigation, generic configuration and network error messages, a per-session AI usage display without secret values, and cleanup hooks for temporary uploads on explicit logout/reset. Update README with exact Cloud steps: push the `SL/` repository contents, choose `streamlit_app.py`, set private sharing to `Only specific people can view this app`, enter the required Secrets, use a demo-only OpenAI key with provider spending limits, configure the fixed SMTP recipient, smoke-test guest/admin/AI/SMTP flows, and remove viewers after the demo.

- [ ] **Step 4: Run the full suite and production-like smoke test**

Run: `cd SL && pytest -v`

Expected: PASS. Then run `streamlit run streamlit_app.py --server.headless true`, verify guest and admin routes manually, and send one PDF request only to the configured controlled recipient.

- [ ] **Step 5: Commit**

```bash
git add SL/streamlit_app.py SL/pages/general.py SL/pages/admin.py SL/README.md SL/tests/test_security_regressions.py
git commit -m "docs: finalize private demo deployment safeguards"
```

## Plan Self-Review

- Spec coverage: Tasks 1–3 cover private deployment assumptions, landing roles, and administrator credentials; Tasks 2, 4, and 6 cover all session-only project, history, and administrator operations; Task 5 covers every requested AI capability; Task 7 covers live supplier collection preview and actual fixed-recipient SMTP sending; Task 8 covers secrecy, cleanup, and deployment verification.
- Placeholder scan: no unassigned implementation steps remain; Cloud Secrets are named but no secret values appear.
- Type consistency: UI code relies only on the `session_store` API; AI and discontinuation services return typed outcomes and never mutate UI state directly.
