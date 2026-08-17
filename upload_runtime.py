"""Process-lifetime upload-session registry shared across Streamlit reruns."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from storage import validate_session_token


_runtime_lock = Lock()
_startup_cleanup_done = False
_active_session_tokens: set[str] = set()


def register_active_session_token(session_token: str) -> str:
    """Validate and retain a live upload-session token for this process."""

    token = validate_session_token(session_token)
    with _runtime_lock:
        _active_session_tokens.add(token)
    return token


def unregister_active_session_token(session_token: str) -> None:
    """Forget a token after its explicit session cleanup has succeeded."""

    token = validate_session_token(session_token)
    with _runtime_lock:
        _active_session_tokens.discard(token)


def active_session_tokens() -> frozenset[str]:
    """Return a locked snapshot for conservative non-startup stale sweeps."""

    with _runtime_lock:
        return frozenset(_active_session_tokens)


def run_startup_cleanup(cleanup: Callable[[frozenset[str]], None]) -> bool:
    """Run cleanup once per interpreter while excluding every live token.

    The callback executes under the registry lock. A concurrent registration
    therefore either appears in the exclusion snapshot or waits until cleanup
    finishes before a new session can create uploads.
    """

    global _startup_cleanup_done
    with _runtime_lock:
        if _startup_cleanup_done:
            return False
        cleanup(frozenset(_active_session_tokens))
        _startup_cleanup_done = True
        return True
