# Final Re-review Fix 2 Implementation Plan

> **For agentic workers:** Implement each checkbox in order with a focused test gate. No Git operations are permitted for this task.

**Goal:** Fix all four Important findings from the final re-review while preserving existing role, session, and failure behavior.

**Architecture:** A small imported registry owns process-lifetime upload cleanup state and synchronizes active-token registration with stale cleanup. General-view helpers enforce read-only approval state and exact current-session file cleanup, while the existing AI boundary continues to own analysis outcomes.

**Tech Stack:** Python 3, Streamlit, pytest, standard-library filesystem APIs

## Global Constraints

- Modify only `SL/`.
- Never follow storage-root, session-directory, or file symlinks during cleanup.
- Never delete an upload path outside the exact current session directory.
- Preserve guest/admin routing, session-only storage, and existing AI failure messages.
- Do not use Git.

---

### Task 1: Process-lifetime upload cleanup registry

**Files:**
- Create: `SL/upload_runtime.py`
- Modify: `SL/storage.py`
- Modify: `SL/streamlit_app.py`
- Modify: `SL/views/general.py`
- Test: `SL/tests/test_security_regressions.py`
- Test: `SL/tests/test_storage.py`

**Interfaces:**
- Produces: `register_active_session_token(token: str) -> str`, `unregister_active_session_token(token: str) -> None`, and `run_startup_cleanup(cleanup: Callable[[frozenset[str]], None]) -> bool`.
- Extends: `cleanup_stale_session_files(..., excluded_session_tokens: Iterable[str] = ()) -> int`.

- [ ] Write regressions that reload the entry module and preserve an active directory while deleting an old prior directory.
- [ ] Add an exclusion regression that preserves an active directory and a symlink target.
- [ ] Implement the locked imported registry and validated no-follow exclusion handling.
- [ ] Register the general session token on every render and unregister it after successful explicit reset.
- [ ] Run the focused startup and storage regressions.

### Task 2: Approved equipment read-only rendering

**Files:**
- Modify: `SL/views/general.py`
- Test: `SL/tests/test_general_workflow.py`

**Interfaces:**
- Consumes: equipment status `approved` written by the administrator review decision.
- Produces: a general renderer that displays the selected approved row without editable controls or mutation actions.

- [ ] Write an approval-then-general-render regression.
- [ ] Add an approved-state branch before construction of the editable status selectbox.
- [ ] Run the focused renderer regression.

### Task 3: Exact project upload cleanup

**Files:**
- Modify: `SL/views/general.py`
- Test: `SL/tests/test_general_workflow.py`

**Interfaces:**
- Produces: `_delete_project_with_uploads(state, project_id, session_token, storage_root) -> None`.
- Consumes: `validated_session_file`, `delete_session_file`, `list_documents`, and the session-store `delete_project` cascade.

- [ ] Write a regression proving project files are removed while sibling and other-session files survive.
- [ ] Write a regression proving a foreign path aborts before physical or metadata mutation.
- [ ] Prevalidate every metadata path, delete each exact file, then call the metadata cascade.
- [ ] Surface cleanup rejection in the project renderer without rerunning or clearing selection.
- [ ] Run the focused deletion regressions.

### Task 4: AI re-review result rendering

**Files:**
- Modify: `SL/views/general.py`
- Test: `SL/tests/test_general_workflow.py`

**Interfaces:**
- Consumes and renders: `AnalysisOutcome` returned by `re_review_project`.

- [ ] Write successful and warning-bearing form-submit regressions.
- [ ] Assign the re-review return value and pass it to `_show_analysis_outcome`.
- [ ] Confirm existing exception rendering remains unchanged.
- [ ] Run the focused re-review regressions.

### Task 5: Verification and handoff

**Files:**
- Create: `SL/.sdd/final-fix2-report.md`

- [ ] Run the complete pytest suite from `SL/`.
- [ ] Run `python -m compileall` for production and tests.
- [ ] Run standalone imports from the `SL/` repository root.
- [ ] Record changed behavior and exact verification results in the final report.
