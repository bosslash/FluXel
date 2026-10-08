$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot

try {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        throw "This script must run on Windows."
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
    }

    if (-not (Test-Path -LiteralPath "fluxel\__about__.py")) {
        throw "FluXel source package is missing: fluxel\__about__.py"
    }

    & uv python install 3.14
    if ($LASTEXITCODE -ne 0) { throw "uv python install failed with exit code $LASTEXITCODE." }

    & uv sync --locked
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed with exit code $LASTEXITCODE." }

    $env:QT_QPA_PLATFORM = "offscreen"
    & uv run python -m unittest discover -s tests -p "test_*.py" -v
    if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
