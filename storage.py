"""Safe, session-scoped temporary-file handling for the Streamlit demo."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from typing import Iterable, Protocol


MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 40 * 1024 * 1024
_ALLOWED_SUFFIXES = frozenset({".pdf", ".pptx", ".xlsx"})
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
STALE_SESSION_SECONDS = 24 * 60 * 60
MAX_CLEANUP_DIRECTORIES = 64


class UploadLike(Protocol):
    """The small portion of Streamlit's ``UploadedFile`` used by this module."""

    name: str

    def getbuffer(self) -> memoryview: ...


@dataclass(frozen=True)
class StoredUpload:
    """Upload metadata retained outside the JSON-only session store."""

    name: str
    path: Path
    size_bytes: int
    content_type: str

    def document_metadata(self) -> dict[str, object]:
        """Return JSON-safe metadata suitable for ``add_document_metadata``."""

        return {
            "name": self.name,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
        }


def session_storage_root() -> Path:
    """Return the sole production upload root, intentionally outside the repo."""

    return Path(tempfile.gettempdir()) / "eic-sl-demo"


def _validated_token(session_token: object) -> str:
    if not isinstance(session_token, str) or not _SAFE_TOKEN.fullmatch(session_token):
        raise ValueError("Invalid session token.")
    return session_token


def validate_session_token(session_token: object) -> str:
    """Return a token only when it is safe for a direct storage-root child."""

    return _validated_token(session_token)


def _session_directory(session_token: object, root: Path) -> Path:
    """Build a lexical child path without resolving a possible symlink target."""

    token = _validated_token(session_token)
    if not isinstance(root, Path):
        raise ValueError("Storage root must be a Path.")

    root_path = Path(os.path.abspath(root))
    directory = root_path / token
    if directory.parent != root_path:
        raise ValueError("Invalid session directory.")
    return directory


def _is_direct_child(path: Path, parent: Path) -> bool:
    """Check containment lexically, without following a symlinked component."""

    return path.parent == parent and path == parent / path.name and path.name not in {"", ".", ".."}


def _ensure_root(root: Path) -> None:
    """Create the known upload root, refusing a symlink in its place."""

    if root.is_symlink():
        raise ValueError("Storage root must not be a symlink.")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Storage root is unavailable.")


def _ensure_session_directory(directory: Path) -> None:
    """Create and validate the exact lexical session child, never a symlink."""

    _ensure_root(directory.parent)
    if directory.is_symlink():
        raise ValueError("Session directory must not be a symlink.")
    try:
        directory.mkdir()
    except FileExistsError:
        pass
    if directory.is_symlink() or not directory.is_dir() or not _is_direct_child(directory, directory.parent):
        raise ValueError("Session directory is unavailable.")


def _open_directory(directory: Path) -> int:
    """Open a directory itself, refusing a symlink even if it changes after checks."""

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(directory, flags)
    except OSError as error:
        raise ValueError("Session directory is unavailable.") from error


def _validate_upload(upload: UploadLike) -> tuple[str, bytes, str]:
    raw_name = getattr(upload, "name", None)
    if not isinstance(raw_name, str) or not raw_name:
        raise ValueError("Upload filename is required.")
    name = Path(raw_name).name
    if not name or name == ".":
        raise ValueError("Upload filename is required.")
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise ValueError("Only PDF, PPTX, and XLSX files are allowed.")
    try:
        contents = bytes(upload.getbuffer())
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Upload contents are unavailable.") from error
    if not contents:
        raise ValueError("Empty files cannot be uploaded.")
    if len(contents) > MAX_FILE_BYTES:
        raise ValueError("Each file must be 20 MiB or smaller.")
    content_type = {
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[suffix]
    return name, contents, content_type


def _available_path(directory: Path, name: str) -> Path:
    """Preserve a normalized filename while avoiding overwrite on duplicates."""

    candidate = directory / name
    if not _is_direct_child(candidate, directory) or candidate.is_symlink():
        raise ValueError("Upload target must not be a symlink.")
    if not candidate.exists():
        return candidate
    source = Path(name)
    number = 2
    while True:
        candidate = directory / f"{source.stem} ({number}){source.suffix}"
        if not _is_direct_child(candidate, directory) or candidate.is_symlink():
            raise ValueError("Upload target must not be a symlink.")
        if not candidate.exists():
            return candidate
        number += 1


def _write_new_file(directory: Path, path: Path, contents: bytes) -> None:
    """Write a new regular file relative to a no-follow session-directory FD."""

    if not _is_direct_child(path, directory) or path.is_symlink():
        raise ValueError("Upload target must not be a symlink.")
    directory_fd = _open_directory(directory)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        file_fd = os.open(path.name, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(file_fd, "wb") as file:
            file.write(contents)
    except OSError as error:
        raise ValueError("Unable to save upload safely.") from error
    finally:
        os.close(directory_fd)


def save_uploads(files: Iterable[UploadLike], session_token: str, root: Path) -> list[StoredUpload]:
    """Validate an upload batch then write it inside exactly one session directory."""

    directory = _session_directory(session_token, root)
    validated = [_validate_upload(file) for file in files]
    total_size = sum(len(contents) for _, contents, _ in validated)
    if total_size > MAX_BATCH_BYTES:
        raise ValueError("combined uploads must be 40 MiB or smaller.")
    if not validated:
        return []

    _ensure_session_directory(directory)
    stored: list[StoredUpload] = []
    for name, contents, content_type in validated:
        path = _available_path(directory, name)
        _write_new_file(directory, path, contents)
        stored.append(StoredUpload(name, path, len(contents), content_type))
    return stored


def cleanup_session_files(session_token: str, root: Path) -> None:
    """Remove only the validated session directory; never the containing root."""

    directory = _session_directory(session_token, root)
    _ensure_root(directory.parent)
    if directory.is_symlink():
        raise ValueError("Session directory must not be a symlink.")
    if not directory.exists():
        return
    if not directory.is_dir() or not _is_direct_child(directory, directory.parent):
        raise ValueError("Session directory is unavailable.")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise ValueError("Safe session cleanup is unavailable.")
    root_fd = _open_directory(directory.parent)
    try:
        shutil.rmtree(directory.name, dir_fd=root_fd)
    finally:
        os.close(root_fd)


def delete_session_file(path: object, session_token: str, root: Path) -> None:
    """Delete one regular file belonging to exactly the named upload session."""

    directory = _session_directory(session_token, root)
    if not isinstance(path, (str, Path)):
        raise ValueError("Upload path is unavailable.")
    target = Path(os.path.abspath(path))
    if not _is_direct_child(target, directory):
        raise ValueError("Upload path is outside this session.")
    if directory.is_symlink() or not directory.is_dir() or target.is_symlink():
        raise ValueError("Upload path is unavailable.")
    try:
        metadata = target.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("Upload path is unavailable.")
    directory_fd = _open_directory(directory)
    try:
        os.unlink(target.name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    finally:
        os.close(directory_fd)


def validated_session_file(path: object, session_token: str, root: Path) -> Path:
    """Return one existing regular file contained by exactly this session."""

    directory = _session_directory(session_token, root)
    if not isinstance(path, (str, Path)):
        raise ValueError("Upload path is unavailable.")
    target = Path(os.path.abspath(path))
    if (
        root.is_symlink()
        or directory.is_symlink()
        or not directory.is_dir()
        or not _is_direct_child(target, directory)
        or target.is_symlink()
    ):
        raise ValueError("Upload path is outside this session.")
    try:
        metadata = target.stat(follow_symlinks=False)
    except OSError as error:
        raise ValueError("Upload path is unavailable.") from error
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
        raise ValueError("Upload path is unavailable.")
    return target


def cleanup_stale_session_files(
    root: Path,
    *,
    older_than_seconds: int = STALE_SESSION_SECONDS,
    max_directories: int = MAX_CLEANUP_DIRECTORIES,
    now: float | None = None,
    excluded_session_tokens: Iterable[str] = (),
) -> int:
    """Remove a bounded number of old, valid session directories.

    Unknown entries and symlinks are ignored.  This makes startup/reset cleanup
    conservative even if the dedicated temporary root has been tampered with.
    """

    if (
        not isinstance(older_than_seconds, int)
        or isinstance(older_than_seconds, bool)
        or older_than_seconds < 0
        or not isinstance(max_directories, int)
        or isinstance(max_directories, bool)
        or not 1 <= max_directories <= MAX_CLEANUP_DIRECTORIES
    ):
        raise ValueError("Invalid stale-session cleanup bounds.")
    try:
        excluded_tokens = frozenset(
            _validated_token(token) for token in excluded_session_tokens
        )
    except TypeError as error:
        raise ValueError("Invalid stale-session cleanup exclusions.") from error
    _ensure_root(root)
    cutoff = (time.time() if now is None else float(now)) - older_than_seconds
    candidates: list[tuple[float, str]] = []
    with os.scandir(root) as entries:
        for scanned, entry in enumerate(entries, start=1):
            if scanned > max_directories * 4:
                break
            if len(candidates) >= max_directories:
                break
            if (
                entry.name in excluded_tokens
                or not _SAFE_TOKEN.fullmatch(entry.name)
                or entry.is_symlink()
            ):
                continue
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                modified = entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                continue
            if modified <= cutoff:
                candidates.append((modified, entry.name))

    removed = 0
    for _, token in sorted(candidates):
        try:
            cleanup_session_files(token, root)
        except (OSError, ValueError):
            continue
        removed += 1
    return removed
