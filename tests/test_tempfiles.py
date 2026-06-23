import os
import time
from pathlib import Path

import pytest

from pdfxlsx.core import tempfiles


def test_can_write_to_creates_dir_and_succeeds(tmp_path):
    target = tmp_path / "nested" / "out"
    assert tempfiles.can_write_to(target) is True
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_can_write_to_fails_on_read_only_dir(tmp_path):
    target = tmp_path / "readonly"
    target.mkdir()
    target.chmod(0o500)
    try:
        if os.access(target, os.W_OK):
            pytest.skip("running as a user that bypasses directory permissions")
        assert tempfiles.can_write_to(target) is False
    finally:
        target.chmod(0o700)


def test_free_space_mb_is_positive(tmp_path):
    assert tempfiles.free_space_mb(tmp_path) > 0


def test_free_space_mb_handles_nonexistent_path(tmp_path):
    missing = tmp_path / "does_not_exist"
    assert tempfiles.free_space_mb(missing) > 0


def test_estimate_required_mb_scales_with_dpi(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"0" * 1024 * 1024)
    low = tempfiles.estimate_required_mb(pdf, dpi=72)
    high = tempfiles.estimate_required_mb(pdf, dpi=300)
    assert high > low
    assert low > 0


def test_estimate_required_mb_has_floor_for_missing_file(tmp_path):
    missing = tmp_path / "missing.pdf"
    assert tempfiles.estimate_required_mb(missing, dpi=300) > 0


def test_run_temp_dir_creates_and_removes_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfiles.paths, "default_temp_root", lambda: tmp_path)
    captured: Path | None = None
    with tempfiles.run_temp_dir() as run_dir:
        captured = run_dir
        assert run_dir.is_dir()
        (run_dir / "scratch.bin").write_bytes(b"x")
    assert captured is not None
    assert not captured.exists()


def test_run_temp_dir_removes_directory_even_on_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfiles.paths, "default_temp_root", lambda: tmp_path)
    captured: Path | None = None
    with pytest.raises(ValueError):
        with tempfiles.run_temp_dir() as run_dir:
            captured = run_dir
            raise ValueError("boom")
    assert captured is not None
    assert not captured.exists()


def test_cleanup_stale_temp_dirs_removes_old_but_keeps_fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfiles.paths, "default_temp_root", lambda: tmp_path)
    stale = tmp_path / "stale_run"
    fresh = tmp_path / "fresh_run"
    stale.mkdir()
    fresh.mkdir()
    old_time = time.time() - 48 * 3600
    os.utime(stale, (old_time, old_time))

    tempfiles.cleanup_stale_temp_dirs(max_age_seconds=24 * 3600)

    assert not stale.exists()
    assert fresh.exists()


def test_cleanup_stale_temp_dirs_handles_missing_root(monkeypatch, tmp_path):
    missing = tmp_path / "never_created"
    monkeypatch.setattr(tempfiles.paths, "default_temp_root", lambda: missing)
    tempfiles.cleanup_stale_temp_dirs()
