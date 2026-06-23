<#
.SYNOPSIS
    Builds the portable Windows distribution of PdfXlsx: a PyInstaller
    --onedir folder with the Tesseract OCR engine and its language data
    bundled inside, zipped, with a SHA-256 checksum next to it.

.DESCRIPTION
    Used both for local developer builds and by
    .github/workflows/release.yml (same script, so CI and local builds can
    never silently diverge). Must be run on Windows with PowerShell 5.1+
    (pwsh on the GitHub Actions windows-latest runner, or Windows
    PowerShell / pwsh locally).

    Requires, on the machine running this script:
      - Python 3.11 or 3.12 on PATH
      - Chocolatey on PATH (already present on windows-latest runners;
        see https://chocolatey.org/install for a local dev machine)

    The resulting zip and .sha256 file are written to the repo root.

.EXAMPLE
    pwsh -File tools/build_windows.ps1
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path "$PSScriptRoot/.."),
    [string]$ArtifactDir = (Join-Path (Resolve-Path "$PSScriptRoot/..") "artifacts")
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

function Write-Step($message) {
    Write-Host ""
    Write-Host "=== $message ===" -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
# 1. Read the application version straight from the source of truth.
# ---------------------------------------------------------------------------
Write-Step "Reading version"
$versionLine = Get-Content "src/pdfxlsx/version.py" | Select-String '__version__\s*=\s*"([^"]+)"'
$version = $versionLine.Matches[0].Groups[1].Value
Write-Host "Version: $version"

# ---------------------------------------------------------------------------
# 2. Install Python build dependencies.
# ---------------------------------------------------------------------------
Write-Step "Installing Python dependencies"
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ---------------------------------------------------------------------------
# 3. Run PyInstaller (--onedir, windowed - see pdfxlsx.spec).
# ---------------------------------------------------------------------------
Write-Step "Running PyInstaller"
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
pyinstaller --noconfirm pdfxlsx.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$distDir = Join-Path $RepoRoot "dist/PdfXlsx"
if (-not (Test-Path $distDir)) { throw "Expected PyInstaller output at $distDir, but it does not exist" }

# ---------------------------------------------------------------------------
# 4. Install Tesseract OCR via Chocolatey (UB-Mannheim community package),
#    then copy the engine binary + DLLs into the portable folder.
# ---------------------------------------------------------------------------
Write-Step "Installing Tesseract OCR (Chocolatey)"
$tesseractInstallDir = "C:\Program Files\Tesseract-OCR"
if (-not (Test-Path (Join-Path $tesseractInstallDir "tesseract.exe"))) {
    choco install tesseract -y --no-progress
    if ($LASTEXITCODE -ne 0) { throw "choco install tesseract failed" }
}
if (-not (Test-Path (Join-Path $tesseractInstallDir "tesseract.exe"))) {
    throw "tesseract.exe not found at $tesseractInstallDir after choco install"
}

Write-Step "Bundling Tesseract engine into the portable folder"
$bundledTesseractDir = Join-Path $distDir "tools/tesseract"
New-Item -ItemType Directory -Force -Path $bundledTesseractDir | Out-Null
Get-ChildItem $tesseractInstallDir -File | Copy-Item -Destination $bundledTesseractDir -Force
Get-ChildItem $tesseractInstallDir -Directory |
    Where-Object { $_.Name -ne "tessdata" } |
    ForEach-Object { Copy-Item $_.FullName -Destination $bundledTesseractDir -Recurse -Force }

# ---------------------------------------------------------------------------
# 5. Fetch just the three language files we need directly from the
#    official tesseract-ocr tessdata_fast distribution, so the bundled set
#    is exact and reproducible regardless of what the Chocolatey package
#    happens to ship.
# ---------------------------------------------------------------------------
Write-Step "Downloading Tesseract language data (eng, rus, osd)"
$tessdataDir = Join-Path $bundledTesseractDir "tessdata"
New-Item -ItemType Directory -Force -Path $tessdataDir | Out-Null
$tessdataBaseUrl = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
foreach ($lang in @("eng", "rus", "osd")) {
    $dest = Join-Path $tessdataDir "$lang.traineddata"
    Invoke-WebRequest -Uri "$tessdataBaseUrl/$lang.traineddata" -OutFile $dest
}

# ---------------------------------------------------------------------------
# 6. Zip the portable folder and compute its SHA-256.
# ---------------------------------------------------------------------------
Write-Step "Zipping portable distribution"
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
$zipName = "PdfXlsx-$version-windows-x64.zip"
$zipPath = Join-Path $ArtifactDir $zipName
Remove-Item $zipPath -ErrorAction SilentlyContinue
Compress-Archive -Path $distDir -DestinationPath $zipPath -CompressionLevel Optimal

Write-Step "Computing SHA-256"
$hash = Get-FileHash -Path $zipPath -Algorithm SHA256
$sha256Path = "$zipPath.sha256"
"$($hash.Hash.ToLower())  $zipName" | Set-Content -Path $sha256Path -Encoding ascii

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Green
Write-Host "  $zipPath"
Write-Host "  $sha256Path"
Write-Host "  SHA-256: $($hash.Hash.ToLower())"
