"""Guest-safe, session-only project workflow for the demo."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from ai_demo import (
    AI_ACTION_LIMIT,
    AIActionLimitError,
    AIConfigurationError,
    AIInputError,
    AIServiceError,
    analyze_project,
    answer_equipment_chat,
    re_review_project,
)
from discontinuation_demo import preview_collection, send_pdf_request, smtp_send_fn
from document_preview import DocumentPreviewError, build_document_preview, render_document_preview
from session_store import (
    append_activity_log,
    add_document_metadata,
    add_equipment,
    create_project,
    create_report_version,
    delete_equipment,
    delete_project,
    get_project,
    get_report_data,
    get_report_version,
    list_chat_messages,
    list_documents,
    list_equipment,
    list_projects,
    list_report_versions,
    remove_document_metadata,
    transition_project,
    update_equipment,
    update_project,
)
from storage import delete_session_file, save_uploads, session_storage_root, validated_session_file
from upload_runtime import register_active_session_token


_SESSION_TOKEN_KEY = "_general_upload_session_token"
_SELECTED_PROJECT_KEY = "_general_selected_project"
_COLLECTION_PREVIEW_ERROR_KEY = "_general_collection_preview_error"


def _secret(secrets: object, name: str) -> str | None:
    """Read a secret only at the UI boundary and never expose lookup failures."""

    try:
        value = secrets.get(name)
    except Exception:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _ai_settings(st: object) -> tuple[str | None, str | None, str | None]:
    return (
        _secret(st.secrets, "OPENAI_API_KEY"),
        _secret(st.secrets, "OPENAI_MODEL"),
        _secret(st.secrets, "TAVILY_API_KEY"),
    )


def _smtp_port(secrets: object) -> str | int | None:
    try:
        value = secrets.get("SMTP_PORT")
    except Exception:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 65535 else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _smtp_settings(st: object) -> dict[str, object]:
    """Read SMTP settings at the Streamlit Secrets boundary only."""

    return {
        "host": _secret(st.secrets, "SMTP_HOST"),
        "port": _smtp_port(st.secrets),
        "user": _secret(st.secrets, "SMTP_USER"),
        "password": _secret(st.secrets, "SMTP_PASSWORD"),
        "recipient": _secret(st.secrets, "REQUEST_RECIPIENT_EMAIL"),
    }


def _show_ai_error(st: object, error: Exception) -> None:
    if isinstance(error, AIActionLimitError):
        st.error(str(error))
    elif isinstance(error, AIInputError):
        st.error(str(error))
    elif isinstance(error, AIConfigurationError):
        st.error("AI 기능을 사용할 수 없습니다. 관리자에게 문의하세요.")
    else:
        st.error("AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요.")


def _safe_snapshot_for_display(version: dict[str, object]) -> dict[str, object]:
    """Remove server-local temporary paths from an immutable UI snapshot."""

    displayed = {key: value for key, value in version.items() if key != "project_content"}
    content = version.get("project_content")
    if not isinstance(content, dict):
        return displayed
    safe_content = dict(content)
    documents = safe_content.get("documents")
    if isinstance(documents, dict):
        safe_content["documents"] = {
            document_id: (
                {key: value for key, value in document.items() if key != "path"}
                if isinstance(document, dict) else document
            )
            for document_id, document in documents.items()
        }
    displayed["project_content"] = safe_content
    return displayed


def _session_token(state: object) -> str:
    """Create a UUID token once; it is UI plumbing, not domain data."""

    token = state.get(_SESSION_TOKEN_KEY)
    if isinstance(token, str):
        try:
            return register_active_session_token(token)
        except ValueError:
            pass
    token = str(uuid4())
    state[_SESSION_TOKEN_KEY] = token
    return register_active_session_token(token)


def _document_bytes(document: dict[str, object], session_token: str) -> bytes | None:
    """Read only a file inside this browser session's temp directory."""

    raw_path = document.get("path")
    if not isinstance(raw_path, str):
        return None
    try:
        path = validated_session_file(raw_path, session_token, session_storage_root())
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _show_analysis_outcome(st: object, outcome: object, *, re_review: bool = False) -> None:
    failed = list(getattr(outcome, "failed", []))
    warnings = list(getattr(outcome, "warnings", []))
    succeeded = list(getattr(outcome, "succeeded", []))
    if failed or warnings:
        st.warning(
            f"분석이 부분 완료되었습니다. 완료 {len(succeeded)}건 · "
            f"설비 실패 {len(failed)}건 · 세부 실패 {len(warnings)}건"
        )
        for message in failed + warnings:
            st.caption(message)
        return
    if re_review:
        st.success("이전 보고서를 보존하고 재검토를 완료했습니다.")
    else:
        st.success(f"{len(succeeded)}개 설비 분석을 완료했습니다.")


def _status_actions(st: object, state: object, project_id: str) -> None:
    """Render closed-set lifecycle transitions through the session store."""

    confirmed, held, resumed = st.columns(3)
    if confirmed.button("검토 확정", key=f"confirm-{project_id}"):
        transition_project(state, project_id, "confirmed")
        st.rerun()
    if held.button("보류", key=f"hold-{project_id}"):
        transition_project(state, project_id, "on_hold")
        st.rerun()
    if resumed.button("재개", key=f"resume-{project_id}"):
        transition_project(state, project_id, "reviewed")
        st.rerun()


def _delete_project_with_uploads(
    state: object, project_id: str, session_token: str, storage_root: Path,
) -> None:
    """Delete exact current-session project uploads, then their metadata."""

    if state.get(_SESSION_TOKEN_KEY) != session_token:
        raise ValueError("Upload session does not match the current session.")
    paths: list[Path] = []
    for document in list_documents(state, project_id):
        raw_path = document.get("path")
        if raw_path is None:
            continue
        paths.append(validated_session_file(raw_path, session_token, storage_root))
    for path in paths:
        delete_session_file(path, session_token, storage_root)
    delete_project(state, project_id)


def _render_project_forms(
    st: object, state: object, project: dict[str, object], session_token: str,
) -> None:
    project_id = str(project["id"])
    st.subheader("프로젝트 편집")
    with st.form(f"project-edit-{project_id}"):
        investment_code = st.text_input("투자 코드", value=str(project.get("investment_code", "")))
        project_name = st.text_input("프로젝트명", value=str(project.get("project_name", "")))
        owner = st.text_input("담당자", value=str(project.get("owner", "")))
        description = st.text_area("설명", value=str(project.get("description", "")))
        submitted = st.form_submit_button("프로젝트 저장")
    if submitted:
        update_project(
            state,
            project_id,
            {
                "investment_code": investment_code,
                "project_name": project_name,
                "owner": owner,
                "description": description,
            },
        )
        st.success("프로젝트를 저장했습니다.")
        st.rerun()

    _status_actions(st, state, project_id)
    if st.button("프로젝트 삭제", key=f"delete-project-{project_id}", type="secondary"):
        try:
            _delete_project_with_uploads(
                state, project_id, session_token, session_storage_root(),
            )
        except (OSError, RuntimeError, ValueError):
            st.error("프로젝트 업로드를 안전하게 정리하지 못했습니다. 삭제를 다시 시도하세요.")
        else:
            state.pop(_SELECTED_PROJECT_KEY, None)
            st.rerun()


def _render_equipment(st: object, state: object, project_id: str) -> None:
    st.subheader("수동 설비 등록")
    with st.form(f"equipment-add-{project_id}", clear_on_submit=True):
        name = st.text_input("설비명")
        equipment_type = st.text_input("설비 유형")
        manufacturer = st.text_input("제조사")
        model_name = st.text_input("모델명")
        submitted = st.form_submit_button("설비 추가")
    if submitted:
        if not name.strip():
            st.error("설비명을 입력하세요.")
        else:
            add_equipment(
                state,
                project_id,
                {
                    "name": name.strip(),
                    "equipment_type": equipment_type.strip(),
                    "manufacturer": manufacturer.strip(),
                    "model_name": model_name.strip(),
                },
            )
            st.rerun()

    equipment_rows = list_equipment(state, project_id)
    if not equipment_rows:
        st.caption("등록된 설비가 없습니다.")
        return
    st.dataframe(equipment_rows, use_container_width=True, hide_index=True)
    choices = {f"{row['name']} ({row['id']})": str(row["id"]) for row in equipment_rows}
    selected_label = st.selectbox("수정할 설비", choices, key=f"equipment-select-{project_id}")
    equipment_id = choices[selected_label]
    current = next(row for row in equipment_rows if row["id"] == equipment_id)
    if str(current.get("status", "pending")) == "approved":
        st.info("관리자가 승인한 설비는 일반 워크플로에서 수정하거나 삭제할 수 없습니다.")
        return
    with st.form(f"equipment-edit-{equipment_id}"):
        name = st.text_input("설비명", value=str(current.get("name", "")), key=f"equipment-name-{equipment_id}")
        equipment_type = st.text_input("설비 유형", value=str(current.get("equipment_type", "")), key=f"equipment-type-{equipment_id}")
        manufacturer = st.text_input("제조사", value=str(current.get("manufacturer", "")), key=f"equipment-maker-{equipment_id}")
        model_name = st.text_input("모델명", value=str(current.get("model_name", "")), key=f"equipment-model-{equipment_id}")
        status = st.selectbox("설비 상태", ("pending", "reviewed", "confirmed"), index=("pending", "reviewed", "confirmed").index(str(current.get("status", "pending"))), key=f"equipment-status-{equipment_id}")
        submitted = st.form_submit_button("설비 저장")
    if submitted:
        update_equipment(state, project_id, equipment_id, {"name": name, "equipment_type": equipment_type, "manufacturer": manufacturer, "model_name": model_name, "status": status})
        st.rerun()
    if st.button("선택 설비 삭제", key=f"equipment-delete-{equipment_id}", type="secondary"):
        delete_equipment(state, project_id, equipment_id)
        st.rerun()


def _render_documents(st: object, state: object, project_id: str, session_token: str) -> None:
    st.subheader("문서")
    files = st.file_uploader("PDF, PPTX, XLSX 업로드", type=["pdf", "pptx", "xlsx"], accept_multiple_files=True, key=f"upload-{project_id}")
    if st.button("선택 문서 저장", key=f"save-documents-{project_id}"):
        try:
            uploads = save_uploads(files or [], session_token, session_storage_root())
            for upload in uploads:
                add_document_metadata(state, project_id, upload.document_metadata())
        except ValueError as error:
            st.error(str(error))
        else:
            if uploads:
                st.success(f"{len(uploads)}개 문서를 저장했습니다.")
                st.rerun()
            st.info("저장할 문서를 선택하세요.")

    documents = list_documents(state, project_id)
    if not documents:
        st.caption("업로드된 문서가 없습니다.")
        return
    for document in documents:
        name = str(document.get("name", "이름 없는 문서"))
        with st.expander(name):
            st.caption(f"{document.get('size_bytes', 0)} bytes · {document.get('uploaded_at', '')}")
            contents = _document_bytes(document, session_token)
            if contents is None:
                st.info("이 세션에서 원본 파일을 찾을 수 없습니다.")
            else:
                st.download_button("원본 다운로드", contents, file_name=name, key=f"download-{document['id']}")
                if st.button("원본 미리보기", key=f"preview-{document['id']}"):
                    try:
                        preview = build_document_preview(name, contents)
                    except DocumentPreviewError:
                        st.error("문서 미리보기를 만들 수 없습니다.")
                    else:
                        render_document_preview(st, preview)
            if st.button("문서 메타데이터 삭제", key=f"document-delete-{document['id']}", type="secondary"):
                raw_path = document.get("path")
                if isinstance(raw_path, str):
                    try:
                        delete_session_file(raw_path, session_token, session_storage_root())
                    except ValueError:
                        st.error("원본 파일을 안전하게 삭제하지 못했습니다.")
                        continue
                remove_document_metadata(state, project_id, str(document["id"]))
                st.rerun()


def _render_ai_actions(st: object, state: object, project_id: str) -> None:
    st.subheader("AI 검토")
    ai_actions = state.get("_ai_action_count", 0)
    if not isinstance(ai_actions, int) or isinstance(ai_actions, bool) or ai_actions < 0:
        ai_actions = 0
    st.caption(f"이 세션의 AI 사용량: {ai_actions} / {AI_ACTION_LIMIT}회")
    api_key, model, tavily_api_key = _ai_settings(st)
    if st.button("AI 분석 시작", key=f"ai-analysis-{project_id}", type="primary"):
        try:
            outcome = analyze_project(
                state, project_id, api_key=api_key, model=model,
                tavily_api_key=tavily_api_key,
            )
        except Exception as error:
            _show_ai_error(st, error)
        else:
            _show_analysis_outcome(st, outcome)

    with st.form(f"ai-re-review-{project_id}"):
        reason = st.text_area("재검토 사유")
        submitted = st.form_submit_button("AI 재검토")
    if submitted:
        try:
            outcome = re_review_project(
                state, project_id, reason, api_key=api_key, model=model,
                tavily_api_key=tavily_api_key,
            )
        except Exception as error:
            _show_ai_error(st, error)
        else:
            _show_analysis_outcome(st, outcome, re_review=True)


def _render_discontinuation_actions(st: object, state: object) -> None:
    """Render non-persistent collection previews and fixed-recipient requests."""

    st.subheader("단종 정보 수집 미리보기")
    st.caption("수집 결과는 미리보기만 제공하며 검토 대기열이나 설비 목록에 자동 등록하지 않습니다.")
    with st.form("discontinuation-preview"):
        supplier = st.selectbox("수집 공급사", ("ABB", "SIEMENS", "HITACHI"))
        model_name = st.text_input("수집 모델명")
        target = st.selectbox("수집 대상", ("PLC", "Drive", "Motor"))
        submitted = st.form_submit_button("수집 미리보기")
    if submitted:
        try:
            preview = preview_collection(supplier, model_name, target)
        except Exception:
            state[_COLLECTION_PREVIEW_ERROR_KEY] = True
        else:
            state.pop(_COLLECTION_PREVIEW_ERROR_KEY, None)
            st.json(preview)

    if state.get(_COLLECTION_PREVIEW_ERROR_KEY) is True:
        st.error("공급사 정보를 가져오지 못했습니다. 잠시 후 다시 시도하세요.")
        retry, sample = st.columns(2)
        if retry.button("다시 시도", key="discontinuation-preview-retry"):
            state.pop(_COLLECTION_PREVIEW_ERROR_KEY, None)
            st.rerun()
        if sample.button("샘플 결과 보기", key="discontinuation-preview-sample"):
            st.json({
                "공급사": "ABB",
                "모델명": "ACS880",
                "대상": "Drive",
                "상태": "샘플 미리보기",
                "안내": "실제 공급사 수집 결과가 아닙니다.",
            })

    st.subheader("공식 PDF 확인 요청")
    st.caption("확인 요청은 Cloud Secrets에 설정된 담당자에게만 전송됩니다.")
    with st.form("pdf-request"):
        supplier = st.selectbox("PDF 공급사", ("TMEIC", "TOSHIBA", "MELCO"))
        model_name = st.text_input("PDF 확인 모델명")
        target = st.selectbox("PDF 확인 대상", ("PLC", "Drive", "Motor"))
        submitted = st.form_submit_button("PDF 확인 요청 보내기")
    if submitted:
        try:
            settings = _smtp_settings(st)
            send_pdf_request(
                supplier, model_name, target, settings, send_fn=smtp_send_fn(settings),
            )
        except Exception:
            st.error("PDF 확인 요청을 보내지 못했습니다. 잠시 후 다시 시도하세요.")
        else:
            append_activity_log(
                state, "send_pdf_request",
                {"supplier": supplier, "model_name": model_name.strip(), "target": target},
            )
            st.success("PDF 확인 요청을 담당자에게 보냈습니다.")


def _render_chat(st: object, state: object, project_id: str) -> None:
    equipment_rows = list_equipment(state, project_id)
    if not equipment_rows:
        return
    st.subheader("설비별 AI 챗봇")
    choices = {f"{row.get('name', '설비')} ({row['id']})": str(row["id"]) for row in equipment_rows}
    selected = st.selectbox("대화할 설비", choices, key=f"chat-equipment-{project_id}")
    equipment_id = choices[selected]
    for index, turn in enumerate(list_chat_messages(state, project_id, equipment_id)):
        with st.chat_message(str(turn.get("role", "assistant"))):
            st.write(str(turn.get("content", "")))
            sources = turn.get("sources", [])
            if isinstance(sources, list):
                for source_index, source in enumerate(sources):
                    if isinstance(source, dict):
                        st.link_button(
                            str(source.get("title") or "웹 출처"), str(source.get("url") or ""),
                            key=f"chat-source-{equipment_id}-{index}-{source_index}",
                        )
    with st.form(f"equipment-chat-{equipment_id}", clear_on_submit=True):
        question = st.text_input("질문")
        submitted = st.form_submit_button("질문 보내기")
    if submitted:
        api_key, model, tavily_api_key = _ai_settings(st)
        try:
            answer_equipment_chat(
                state, project_id, equipment_id, question, api_key=api_key,
                model=model, tavily_api_key=tavily_api_key,
            )
        except Exception as error:
            _show_ai_error(st, error)
        else:
            st.rerun()


def _render_reports(st: object, state: object, project_id: str) -> None:
    st.subheader("검토 보고서")
    report_data = get_report_data(state, project_id)
    if report_data:
        st.caption(
            f"분석 설비 {report_data.get('total_equipment', 0)}개 · "
            f"교체 검토 {report_data.get('recommended_replacements', 0)}개"
        )
        for row in list_equipment(state, project_id):
            report = row.get("report")
            if not isinstance(report, dict) or "technical_opinion" not in report:
                continue
            with st.expander(str(row.get("name", "설비"))):
                st.metric("교체 필요성 점수", report.get("score", 0))
                st.write(report.get("technical_opinion", ""))
                st.markdown("**평가 인자**")
                st.json(report.get("extracted_factors", {}))
                risks = report.get("risk_checklist", [])
                if report.get("risk_checklist_status") == "failed":
                    st.warning("리스크 체크리스트 생성이 실패했습니다. 다시 분석하세요.")
                elif risks:
                    st.markdown("**리스크 체크리스트**")
                    for risk in risks:
                        st.write(f"- {risk}")
                new_model = report.get("new_model_review")
                if report.get("new_model_review_status") == "failed":
                    st.warning("신규 모델 검토가 실패했습니다. 다시 분석하세요.")
                if isinstance(new_model, dict):
                    st.markdown("**신규 모델 검토**")
                    st.write(str(new_model.get("summary", "")))
                    if new_model.get("limitation"):
                        st.caption(str(new_model["limitation"]))
                    for index, source in enumerate(new_model.get("sources", [])):
                        if isinstance(source, dict):
                            st.link_button(
                                str(source.get("title") or "웹 출처"), str(source.get("url") or ""),
                                key=f"model-source-{row['id']}-{index}",
                            )
    else:
        st.info("아직 생성된 분석 보고서가 없습니다.")

    if st.button("현재 상태를 보고서 버전으로 저장", key=f"report-version-{project_id}"):
        create_report_version(state, project_id, "일반 사용자 수동 스냅샷")
        st.rerun()

    versions = list_report_versions(state, project_id)
    if not versions:
        st.caption("저장된 보고서 버전이 없습니다.")
        return
    version_choices = {f"{row['timestamp']} · {row['reason']}": str(row["id"]) for row in versions}
    selected = st.selectbox("보고서 버전", version_choices, key=f"report-version-select-{project_id}")
    version = get_report_version(state, version_choices[selected])
    st.json(_safe_snapshot_for_display(version))


def render_general_page() -> None:
    """Render the guest-accessible, session-only project and AI workflow."""

    import streamlit as st

    state = st.session_state
    session_token = _session_token(state)
    st.title("EIC 교체 타당성 검토")
    st.warning("이 화면의 프로젝트와 업로드 문서는 현재 브라우저 세션에서만 유지되며, 새로고침·세션 만료 시 사라질 수 있습니다.")

    projects = list_projects(state)
    st.subheader("프로젝트 목록")
    st.dataframe(projects, use_container_width=True, hide_index=True)
    with st.form("project-create", clear_on_submit=True):
        code = st.text_input("새 투자 코드")
        name = st.text_input("새 프로젝트명")
        owner = st.text_input("새 담당자")
        description = st.text_area("새 프로젝트 설명")
        create_submitted = st.form_submit_button("프로젝트 만들기")
    if create_submitted:
        if not name.strip():
            st.error("프로젝트명을 입력하세요.")
        else:
            project_id = create_project(state, {"investment_code": code.strip(), "project_name": name.strip(), "owner": owner.strip(), "description": description.strip()})
            state[_SELECTED_PROJECT_KEY] = project_id
            st.rerun()

    choices = {f"{row['project_name']} ({row['status']})": str(row["id"]) for row in projects}
    if not choices:
        return
    selected_id = state.get(_SELECTED_PROJECT_KEY)
    index = list(choices.values()).index(selected_id) if selected_id in choices.values() else 0
    selected_label = st.selectbox("작업할 프로젝트", choices, index=index)
    project_id = choices[selected_label]
    state[_SELECTED_PROJECT_KEY] = project_id
    project = get_project(state, project_id)
    _render_project_forms(st, state, project, session_token)
    _render_equipment(st, state, project_id)
    _render_documents(st, state, project_id, session_token)
    _render_ai_actions(st, state, project_id)
    _render_discontinuation_actions(st, state)
    _render_reports(st, state, project_id)
    _render_chat(st, state, project_id)
