"""Smoke test for the PyInstaller-built portable distribution.

Builds the real `pdfxlsx.spec` bundle and launches the resulting
executable to confirm it starts up and stays running (i.e. the
PySide6 event loop comes up cleanly with no missing-module crashes).
Not part of the default test run (see `addopts` in pyproject.toml)
because it is slow and writes build artifacts to the repo root; run
explicitly with `pytest -m smoke`.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_frozen_app_launches_without_crashing():
    dist_dir = REPO_ROOT / "dist" / "PdfXlsx"
    shutil.rmtree(REPO_ROOT / "dist", ignore_errors=True)
    shutil.rmtree(REPO_ROOT / "build", ignore_errors=True)

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "pdfxlsx.spec"],
        cwd=REPO_ROOT,
        check=True,
    )

    exe = dist_dir / ("PdfXlsx.exe" if sys.platform == "win32" else "PdfXlsx")
    assert exe.exists(), f"expected PyInstaller output at {exe}"

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.Popen([str(exe)], cwd=dist_dir, env=env)
    try:
        returncode = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=10)
    else:
        pytest.fail(f"app exited on its own (code {returncode}) instead of staying open")
