# Offline Operation: Verification

PdfXlsx is designed to **never** access the network, open a listening port,
or transmit any data once it is running. This document records what was
checked to verify that, and how to re-verify it yourself.

## Scope

"Runtime" means everything that executes when a user runs `PdfXlsx.exe` (or
`python -m pdfxlsx` in development). It explicitly excludes the *build*
process (`tools/build_windows.ps1`, `.github/workflows/*.yml`), which does
need network access — to `pip install` dependencies and to download the
Tesseract OCR engine and its language data — but only on the developer's or
CI's machine, never on an end user's machine, and never as part of the
shipped program.

## Static source audit

A search of `src/pdfxlsx/` (the entire runtime code, both `core/` and
`gui/`) for any network-capable API turns up nothing:

```
$ grep -rEn "socket\.|urllib|requests\.|httpx|aiohttp|paramiko|telnetlib|xmlrpc|ftplib|smtplib|ssl\.wrap|http\.server|wsgiref|QtNetwork|QNetworkAccessManager|QTcpSocket|QUdpSocket|urlopen" src/
(no matches)
```

No file under `src/` imports `socket`, `urllib`, `http.client`, `requests`,
`httpx`, `aiohttp`, or any `PySide6.QtNetwork` class. There is no listening
socket, no outbound HTTP client, and no DNS resolution anywhere in the
application's own code.

Re-run this check yourself at any time:

```bash
grep -rEn "socket\.|urllib|requests\.|httpx|aiohttp|paramiko|telnetlib|xmlrpc|ftplib|smtplib|ssl\.wrap|http\.server|wsgiref|QtNetwork|QNetworkAccessManager|QTcpSocket|QUdpSocket|urlopen" src/
```

This audit should be re-run whenever a runtime dependency in
`requirements.txt` is added or upgraded.

## Runtime dependencies and why they cannot reach the network

`requirements.txt` (the only packages bundled into the frozen Windows
build — see `THIRD_PARTY_LICENSES.txt` for the full list):

| Package | Role | Network capability |
|---|---|---|
| PySide6 | GUI toolkit | Ships a `QtNetwork` module, but it is never imported anywhere in this codebase (confirmed above); PyInstaller only bundles modules that are actually imported. |
| pdfplumber | PDF text/table parsing | Pure local file parsing; no network code. |
| pypdfium2 | PDF rendering (via Google's PDFium) | Local rendering library; no network code. |
| pytesseract | Thin wrapper that shells out to a local `tesseract` binary | Invokes a local subprocess only (`paths.tesseract_executable()` resolves to the bundled `.exe`, never a network resource). |
| openpyxl | `.xlsx` writing | Local file I/O only. |
| opencv-python-headless | Image processing for table-line detection | Local image processing only; the headless variant additionally has no GUI/display backend at all. |
| numpy | Array math | No I/O capability of its own. |
| Pillow | Image loading/manipulation | Local image I/O only. |

None of these libraries open sockets or make HTTP requests as part of the
functionality PdfXlsx actually exercises.

## The local OCR engine never touches the network

The bundled Tesseract OCR binary (`tools/tesseract/tesseract.exe` in the
frozen build) is a local, offline executable: it reads an image and a
local `.traineddata` language file from `tools/tesseract/tessdata/` and
returns recognized text. It is invoked as a local subprocess by
`pytesseract`/`ocr_engine.py` with no arguments or environment variables
that could direct it elsewhere. `ocr_engine.configure()` explicitly points
`pytesseract.pytesseract.tesseract_cmd` at the bundled binary path and sets
`TESSDATA_PREFIX` to the bundled `tessdata/` directory — there is no
fallback to a network-hosted model or API in a frozen build (the only
fallback, to a *system-installed* `tesseract`, is gated behind
`not is_frozen()` and exists solely so tests can run in development
without vendoring binaries into the git repository).

## Build-time network access (not part of the shipped program)

The only network access anywhere in this project happens before a release
exists, on the build machine:

- `pip install -r requirements-dev.txt` / `requirements.txt` — installs
  build/runtime Python dependencies from PyPI.
- `tools/build_windows.ps1` installs Tesseract OCR via
  `choco install tesseract` and downloads `eng.traineddata`,
  `rus.traineddata`, `osd.traineddata` directly from the official
  `tesseract-ocr/tessdata_fast` GitHub repository.

Both happen only inside `tools/build_windows.ps1` / GitHub Actions runners,
never inside the application that ends up in `dist/PdfXlsx/`. Once built,
the resulting folder is self-contained: every binary and data file it needs
(`PdfXlsx.exe`, the PyInstaller `_internal/` runtime, and
`tools/tesseract/` with its language data) is already inside it.

## No secrets, tokens, or telemetry

- There are no API keys, tokens, or credentials anywhere in this
  repository or in the shipped program — there is nothing for the program
  to authenticate to, since it never makes a network call.
- The only secret referenced anywhere in this repository is the
  GitHub-managed `secrets.GITHUB_TOKEN` used by
  `.github/workflows/release.yml` to create a GitHub Release; it exists
  only in the CI environment, is provided automatically by GitHub Actions,
  and is never written to the repository, the build artifacts, or the
  shipped application.
- There is no telemetry, crash reporting, update checking, or analytics of
  any kind in the application.

## How to verify this yourself, end to end

1. Build (or download) the portable distribution.
2. Disconnect the test machine from the network entirely (unplug Ethernet
   and disable Wi-Fi, or run inside a VM with no virtual network adapter).
3. Run `PdfXlsx.exe` and convert a representative set of PDFs (text,
   scanned, mixed, rotated, password-protected, corrupt).
4. Confirm every feature still works identically, and that the operating
   system's connection/firewall indicators show no outbound activity from
   `PdfXlsx.exe` at any point.
