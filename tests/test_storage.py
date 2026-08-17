from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile

import pytest

from storage import (
    MAX_BATCH_BYTES,
    MAX_FILE_BYTES,
    cleanup_session_files,
    cleanup_stale_session_files,
    delete_session_file,
    save_uploads,
    session_storage_root,
)


class Upload:
    def __init__(self, name: str, contents: bytes) -> None:
        self.name = name
        self._contents = contents

    def getbuffer(self) -> memoryview:
        return BytesIO(self._contents).getbuffer()


def test_upload_is_saved_under_its_session_directory(tmp_path: Path) -> None:
    stored = save_uploads([Upload("../../unsafe.PDF", b"%PDF-1.4")], "session-a", tmp_path)

    assert stored[0].path.parent == tmp_path / "session-a"
    assert stored[0].path.name == "unsafe.PDF"
    assert stored[0].path.read_bytes() == b"%PDF-1.4"


def test_default_storage_root_is_session_only_system_temp_directory() -> None:
    assert session_storage_root() == Path(tempfile.gettempdir()) / "eic-sl-demo"


@pytest.mark.parametrize(
    "uploads",
    (
        [Upload("unsafe.txt", b"not allowed")],
        [Upload("empty.pdf", b"")],
        [Upload("too-large.pdf", b"x" * (MAX_FILE_BYTES + 1))],
        [
            Upload("first.pdf", b"x" * (MAX_FILE_BYTES // 2 + 1)),
            Upload("second.PPTX", b"x" * (MAX_FILE_BYTES // 2 + 1)),
            Upload("third.xlsx", b"x" * (MAX_FILE_BYTES + 1)),
        ],
    ),
)
def test_upload_rejects_invalid_type_and_size_limits(tmp_path: Path, uploads: list[Upload]) -> None:
    with pytest.raises(ValueError):
        save_uploads(uploads, "session-a", tmp_path)


def test_upload_rejects_batch_larger_than_limit_without_writing(tmp_path: Path) -> None:
    uploads = [
        Upload("first.pdf", b"x" * (MAX_BATCH_BYTES // 3 + 1)),
        Upload("second.xlsx", b"x" * (MAX_BATCH_BYTES // 3 + 1)),
        Upload("third.pptx", b"x" * (MAX_BATCH_BYTES // 3 + 1)),
    ]

    with pytest.raises(ValueError, match="combined"):
        save_uploads(uploads, "session-a", tmp_path)

    assert not (tmp_path / "session-a").exists()


def test_cleanup_only_removes_the_validated_session_directory(tmp_path: Path) -> None:
    target = tmp_path / "session-a"
    sibling = tmp_path / "session-b"
    target.mkdir()
    sibling.mkdir()
    (target / "document.pdf").write_bytes(b"data")
    (sibling / "keep.pdf").write_bytes(b"data")

    cleanup_session_files("session-a", tmp_path)

    assert not target.exists()
    assert (sibling / "keep.pdf").exists()


def test_document_deletion_removes_exact_file_and_keeps_session_siblings(tmp_path: Path) -> None:
    session = tmp_path / "session-a"
    session.mkdir()
    target = session / "remove.pdf"
    keep = session / "keep.pdf"
    target.write_bytes(b"remove")
    keep.write_bytes(b"keep")

    delete_session_file(target, "session-a", tmp_path)

    assert not target.exists()
    assert keep.read_bytes() == b"keep"


def test_stale_cleanup_is_bounded_and_ignores_recent_and_symlink_entries(tmp_path: Path) -> None:
    stale = tmp_path / "stale-session"
    recent = tmp_path / "recent-session"
    victim = tmp_path.parent / f"{tmp_path.name}-victim"
    stale.mkdir()
    recent.mkdir()
    victim.mkdir()
    (victim / "keep.pdf").write_bytes(b"keep")
    (tmp_path / "linked-session").symlink_to(victim, target_is_directory=True)
    import os

    os.utime(stale, (100, 100))
    os.utime(recent, (900, 900))

    removed = cleanup_stale_session_files(
        tmp_path, older_than_seconds=500, max_directories=2, now=1000,
    )

    assert removed == 1
    assert not stale.exists()
    assert recent.exists()
    assert (victim / "keep.pdf").read_bytes() == b"keep"


def test_stale_cleanup_never_removes_more_than_the_explicit_bound(tmp_path: Path) -> None:
    import os

    for name in ("session-a", "session-b", "session-c"):
        directory = tmp_path / name
        directory.mkdir()
        os.utime(directory, (100, 100))

    removed = cleanup_stale_session_files(
        tmp_path, older_than_seconds=1, max_directories=2, now=1000,
    )

    assert removed == 2
    assert len([path for path in tmp_path.iterdir() if path.is_dir()]) == 1


def test_stale_cleanup_excludes_active_token_and_never_follows_symlink(tmp_path: Path) -> None:
    import os

    stale = tmp_path / "stale-session"
    active = tmp_path / "active-session"
    victim = tmp_path.parent / f"{tmp_path.name}-active-victim"
    stale.mkdir()
    active.mkdir()
    victim.mkdir()
    (active / "active.pdf").write_bytes(b"active")
    (victim / "keep.pdf").write_bytes(b"keep")
    (tmp_path / "linked-session").symlink_to(victim, target_is_directory=True)
    for directory in (stale, active):
        os.utime(directory, (100, 100))

    removed = cleanup_stale_session_files(
        tmp_path,
        older_than_seconds=1,
        now=1000,
        excluded_session_tokens=("active-session",),
    )

    assert removed == 1
    assert not stale.exists()
    assert (active / "active.pdf").read_bytes() == b"active"
    assert (victim / "keep.pdf").read_bytes() == b"keep"


def test_upload_rejects_session_directory_symlink_without_writing_to_victim(tmp_path: Path) -> None:
    victim = tmp_path / "session-b"
    victim.mkdir()
    keep = victim / "keep.pdf"
    keep.write_bytes(b"keep")
    (tmp_path / "session-a").symlink_to(victim, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        save_uploads([Upload("new.pdf", b"new")], "session-a", tmp_path)

    assert keep.read_bytes() == b"keep"
    assert not (victim / "new.pdf").exists()


def test_cleanup_rejects_session_directory_symlink_without_deleting_victim(tmp_path: Path) -> None:
    victim = tmp_path / "session-b"
    victim.mkdir()
    keep = victim / "keep.pdf"
    keep.write_bytes(b"keep")
    (tmp_path / "session-a").symlink_to(victim, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        cleanup_session_files("session-a", tmp_path)

    assert keep.read_bytes() == b"keep"
    assert victim.is_dir()


def test_upload_rejects_symlinked_file_target(tmp_path: Path) -> None:
    session = tmp_path / "session-a"
    victim = tmp_path / "victim.pdf"
    session.mkdir()
    victim.write_bytes(b"keep")
    (session / "new.pdf").symlink_to(victim)

    with pytest.raises(ValueError, match="symlink"):
        save_uploads([Upload("new.pdf", b"new")], "session-a", tmp_path)

    assert victim.read_bytes() == b"keep"


@pytest.mark.parametrize("token", ("", "../session-a", "session/a", "session a"))
def test_storage_rejects_unsafe_session_tokens(tmp_path: Path, token: str) -> None:
    with pytest.raises(ValueError):
        save_uploads([Upload("safe.pdf", b"data")], token, tmp_path)
    with pytest.raises(ValueError):
        cleanup_session_files(token, tmp_path)
