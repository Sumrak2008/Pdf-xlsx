# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable Windows build.

Builds a one-folder (--onedir) distribution: PdfXlsx.exe plus an
_internal/ runtime folder, no installer, no admin rights needed. The
bundled Tesseract OCR engine and its language data are NOT included by
PyInstaller itself - the build scripts (tools/build_windows.ps1 locally,
.github/workflows/release.yml in CI) copy `tools/tesseract/` into the
finished dist/PdfXlsx/ folder as a separate step, after PyInstaller runs.
"""

from pathlib import Path

block_cipher = None

a = Analysis(
    ["src/pdfxlsx/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfXlsx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PdfXlsx",
)
