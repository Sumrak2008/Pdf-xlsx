"""Per-run temporary working directory with guaranteed cleanup."""

from __future__ import annotations

import contextlib
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from pdfxlsx.core import paths


@contextlib.contextmanager
def run_temp_dir() -> Iterator[Path]:
    """Create an isolated temp folder for one conversion run and remove it.

    The folder (and everything written into it, e.g. rasterized page images
    used for OCR) is deleted when the `with` block exits, whether processing
    finished, raised, or was cancelled.
    """
    root = paths.default_temp_root()
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = root / name
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield run_dir
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def free_space_mb(path: Path) -> float:
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    return usage.free / (1024 * 1024)


def can_write_to(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write_test_{uuid.uuid4().hex}.tmp"
        probe.write_bytes(b"0")
        probe.unlink()
        return True
    except OSError:
        return False


def estimate_required_mb(pdf_path: Path, dpi: int) -> float:
    """Rough upper-bound estimate of temp disk usage for rasterizing pages.

    Used only for an early, user-friendly disk-space warning; not a hard
    physical limit. Assumes ~ (dpi/72)^2 * 8 bytes/px * a4-ish page count
    proxy derived from the PDF file size, plus a fixed safety margin.
    """
    size_mb = pdf_path.stat().st_size / (1024 * 1024) if pdf_path.exists() else 1.0
    scale = (dpi / 72.0) ** 2
    estimate = max(20.0, size_mb * 4.0) * scale / 17.0
    return estimate + 50.0


def cleanup_stale_temp_dirs(max_age_seconds: int = 24 * 3600) -> None:
    """Remove leftover temp folders from previous runs that crashed/were killed."""
    root = paths.default_temp_root()
    now = time.time()
    if not root.exists():
        return
    for child in root.iterdir():
        try:
            if child.is_dir() and (now - child.stat().st_mtime) > max_age_seconds:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _is_hidden_copy_path(path: Path) -> bool:
    """Sanity helper used by tests: ensure we never write outside run_temp_dir."""
    return os.path.commonpath([str(path), str(paths.default_temp_root())]) == str(
        paths.default_temp_root()
    )
