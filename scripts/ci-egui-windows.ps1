$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $repoRoot "fluxel-egui")

try {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        throw "This script must run on Windows."
    }

    if (-not (Get-Command rustup -ErrorAction SilentlyContinue)) {
        throw "rustup is required: https://rustup.rs/"
    }

    & rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
    if ($LASTEXITCODE -ne 0) { throw "Rust installation failed with exit code $LASTEXITCODE." }

    & cargo +1.95.0 fmt --all -- --check
    if ($LASTEXITCODE -ne 0) { throw "Formatting check failed with exit code $LASTEXITCODE." }

    & cargo +1.95.0 test --all-targets --locked
    if ($LASTEXITCODE -ne 0) { throw "Tests failed with exit code $LASTEXITCODE." }

    & cargo +1.95.0 clippy --all-targets --locked -- -D warnings
    if ($LASTEXITCODE -ne 0) { throw "Clippy failed with exit code $LASTEXITCODE." }

    & cargo +1.95.0 build --release --locked
    if ($LASTEXITCODE -ne 0) { throw "Release build failed with exit code $LASTEXITCODE." }

    New-Item -ItemType Directory -Force -Path "dist" | Out-Null
    Copy-Item -LiteralPath "target\release\fluxel-egui.exe" -Destination "dist\Fluxel.exe" -Force
}
finally {
    Pop-Location
}
