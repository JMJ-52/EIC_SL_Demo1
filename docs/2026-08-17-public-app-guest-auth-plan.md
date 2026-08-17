# Public App Guest Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a single Secrets-backed guest account before users can access the public Streamlit demo's general workflow.

**Architecture:** Keep roles unchanged (`guest` and `admin`) and add a dedicated guest credential verifier alongside the administrator verifier. The landing page owns only form state and routing; `auth.py` performs the fail-closed secret comparison. Secrets names and public-hosting guidance are documented without values.

**Tech Stack:** Python 3.11, Streamlit, pytest, standard-library `hmac`.

## Global Constraints

- Store only `GUEST_USERNAME` and `GUEST_PASSWORD` values in Streamlit Secrets; never in source, tests, logs, or documentation.
- Treat missing, non-string, and mismatching credential values identically.
- Use `hmac.compare_digest` for both username and password comparisons.
- Do not allow unauthenticated sessions to render general or admin pages.
- Keep existing administrator login semantics and keys unchanged.

---

### Task 1: Add guest credential verification and landing flow

**Files:**
- Modify: `auth.py`
- Modify: `views/landing.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `authenticate_guest(username: object, password: object, secrets: Mapping[str, object]) -> bool`
- Consumes: `enter_guest(state)` and `append_login_log(state, user_id, outcome)`.

- [ ] **Step 1: Write failing unit tests**

```python
from auth import authenticate_guest


def test_guest_authentication_requires_both_guest_secret_values() -> None:
    secrets = {"GUEST_USERNAME": "guest", "GUEST_PASSWORD": "correct"}
    assert authenticate_guest("guest", "correct", secrets) is True
    assert authenticate_guest("guest", "wrong", secrets) is False
    assert authenticate_guest("wrong", "correct", secrets) is False


def test_guest_and_admin_credentials_are_separate() -> None:
    secrets = {
        "GUEST_USERNAME": "guest", "GUEST_PASSWORD": "guest-password",
        "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": "admin-password",
    }
    assert authenticate_guest("admin", "admin-password", secrets) is False
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/test_auth.py -q`

Expected: failure importing `authenticate_guest`.

- [ ] **Step 3: Implement the verifier and guest form**

```python
def authenticate_guest(username: object, password: object, secrets: Mapping[str, object]) -> bool:
    configured_username = secrets.get("GUEST_USERNAME")
    configured_password = secrets.get("GUEST_PASSWORD")
    if not all(isinstance(value, str) for value in (
        username, password, configured_username, configured_password,
    )):
        return False
    return hmac.compare_digest(username, configured_username) & hmac.compare_digest(
        password, configured_password,
    )
```

Render a guest form after the `초대 이용자` selection. On success clear both guest widget values, call `enter_guest`, log `guest`/`success`, clear only guest form-open state, then rerun. On failure show `초대 이용자 인증에 실패했습니다.` and preserve no password in the session. Extend `logout` to clear all guest state and widget keys.

- [ ] **Step 4: Run focused authentication tests**

Run: `pytest tests/test_auth.py -q`

Expected: all guest and admin authentication tests pass.

### Task 2: Update the Cloud secret contract and deployment guidance

**Files:**
- Modify: `streamlit_app.py`
- Modify: `README.md`
- Test: `tests/test_app_bootstrap.py`

**Interfaces:**
- Produces: `required_secret_names() -> tuple[str, ...]` containing both guest secret names.

- [ ] **Step 1: Update the bootstrap assertion**

```python
assert set(required_secret_names()) == {
    "GUEST_USERNAME", "GUEST_PASSWORD", "ADMIN_USERNAME", "ADMIN_PASSWORD",
    "OPENAI_API_KEY", "OPENAI_MODEL", "TAVILY_API_KEY", "SMTP_HOST",
    "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "REQUEST_RECIPIENT_EMAIL",
}
```

- [ ] **Step 2: Run the bootstrap test to verify it fails**

Run: `pytest tests/test_app_bootstrap.py -q`

Expected: required Secrets list lacks the guest values.

- [ ] **Step 3: Update secret names and README**

Insert the two guest keys before the administrator keys in `required_secret_names()` and the README Secrets block. Replace Community Cloud's obsolete private-sharing directions with public-deployment instructions: set both guest Secrets, give the URL only to intended users, and describe that this application gate does not make a public URL or static assets private.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`

Expected: all tests pass with no secret values printed.

### Task 3: Commit and deploy

**Files:**
- Modify: tracked implementation, tests, and documentation from Tasks 1–2.

- [ ] **Step 1: Inspect the staged change set**

Run: `git diff --check && git status --short`

Expected: only the specific `SL/` authentication, test, and documentation changes are included.

- [ ] **Step 2: Commit the scoped change**

Run: `git add SL/auth.py SL/views/landing.py SL/streamlit_app.py SL/tests/test_auth.py SL/tests/test_app_bootstrap.py SL/README.md SL/docs/2026-08-17-public-app-guest-auth-design.md SL/docs/2026-08-17-public-app-guest-auth-plan.md && git commit -m "feat: require guest login for public demo"`

Expected: a new commit contains only the listed paths.

- [ ] **Step 3: Deploy via Streamlit Community Cloud**

Select the GitHub repository and branch containing the `SL/` app, set main file to `streamlit_app.py`, then enter the required Secrets. Never enter secrets into the repository. Confirm immediately before publishing and before transmitting any Secret values.

- [ ] **Step 4: Smoke test the public URL**

Verify: an unauthenticated page shows only the two entry choices; a wrong guest login is rejected; correct guest login exposes only the general workflow; administrator credentials cannot authenticate as the guest; logout returns to the entry screen.
