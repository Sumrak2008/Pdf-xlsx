"""Resolution of file-system locations: bundled tools, temp dir, app root.

The shipped Windows build is a folder produced by PyInstaller (`--onedir`).
Its layout is::

    PdfXlsx/
        PdfXlsx.exe
        _internal/...            (PyInstaller runtime, created automatically)
        tools/
            tesseract/
                tesseract.exe
                *.dll
                tessdata/
                    rus.traineddata
                    eng.traineddata
                    osd.traineddata

Everything is resolved relative to the executable's own directory so the
program works no matter where the folder is unzipped, and never consults
the system PATH or registry for these binaries.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Directory containing the executable (frozen) or the repo root (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # src/pdfxlsx/core/paths.py -> repo root is 3 levels up from src/pdfxlsx/core
    return Path(__file__).resolve().parents[3]


def tools_dir() -> Path:
    return app_root() / "tools"


def tesseract_dir() -> Path:
    return tools_dir() / "tesseract"


def tessdata_dir() -> Path:
    return tesseract_dir() / "tessdata"


def tesseract_executable() -> Path | None:
    """Locate the bundled tesseract binary.

    In a frozen build this MUST be the bundled copy (no PATH fallback,
    per the offline/no-system-dependency requirement). In dev mode (running
    from source on a developer machine, e.g. this Linux sandbox) we allow
    falling back to a system installation purely to make local development
    and `pytest` possible without bundling binaries into the git repo.
    """
    bundled_name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    bundled = tesseract_dir() / bundled_name
    if bundled.exists():
        return bundled
    if is_frozen():
        return None
    system_tesseract = shutil.which("tesseract")
    return Path(system_tesseract) if system_tesseract else None


def tessdata_prefix() -> Path | None:
    """Directory to pass as TESSDATA_PREFIX, bundled copy preferred."""
    bundled = tessdata_dir()
    if bundled.exists() and any(bundled.glob("*.traineddata")):
        return bundled
    if is_frozen():
        return None
    for candidate in (
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tessdata"),
    ):
        if candidate.exists():
            return candidate
    return None


def default_temp_root() -> Path:
    """Base directory for this app's own temporary working folders.

    A subfolder next to the executable (rather than the shared OS temp
    directory) is used deliberately: it keeps all scratch files on the same
    local disk/volume as the program itself (simplifying the free-space
    check), makes cleanup trivially visible to the user, and guarantees the
    temp data never leaves the portable folder, let alone the machine.
    """
    base = app_root() / "_temp"
    base.mkdir(parents=True, exist_ok=True)
    return base
