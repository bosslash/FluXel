# Fluxel 配布パイプライン（主成果物: Inno インストーラー）
# リポジトリルートで実行:  powershell -ExecutionPolicy Bypass -File packaging\build-release.ps1
#
# 既定の成果物（配布用）
#   dist\installer\Fluxel_Setup_v0.3.0-20260801.exe
#   dist\release\Fluxel_Setup_v0.3.0-20260801_installer.zip … 上記 EXE を 1 本だけ入れた ZIP（配布しやすい形）
#
# 任意
#   FLUXEL_PORTABLE_ZIP=1 … 追加で dist\release\Fluxel_portable_*.zip（PyInstaller onedir の詰め物）
#
# 開発用
#   FLUXEL_SKIP_INNO=1 … Inno を試さない（PyInstaller の dist\Fluxel\ のみ。配布用としては未完成）
#
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$aboutText = Get-Content -LiteralPath "fluxel\__about__.py" -Raw
if ($aboutText -notmatch 'APP_SEMVER\s*=\s*"([^"]+)"') {
    throw "APP_SEMVER was not found in fluxel\__about__.py"
}
$AppSemVer = $Matches[1]
if ($aboutText -notmatch 'APP_RELEASE_DATE\s*=\s*"([0-9]{8})"') {
    throw "APP_RELEASE_DATE was not found in fluxel\__about__.py"
}
$ReleaseDate = $Matches[1]
$versionParts = $AppSemVer.Split(".")
if ($versionParts.Count -ne 3) {
    throw "APP_SEMVER must contain three numeric components."
}
$ReleaseVersion = "v${AppSemVer}-${ReleaseDate}"
$InstallerVersion = "$($versionParts[0]).$($versionParts[1]).${ReleaseDate}"
$FileVersion = "$($versionParts[0]).$($versionParts[1]).$($versionParts[2]).0"

function Find-InnoISCC {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 5\ISCC.exe"
    )
    foreach ($p in $candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }

    foreach ($hive in @("HKLM:\SOFTWARE\WOW6432Node", "HKLM:\SOFTWARE")) {
        $key = Join-Path $hive "Microsoft\Windows\CurrentVersion\App Paths\ISCC.exe"
        if (Test-Path -LiteralPath $key) {
            try {
                $def = (Get-ItemProperty -LiteralPath $key -ErrorAction Stop).'(default)'
                if ($def -and (Test-Path -LiteralPath $def)) { return $def }
            } catch {}
        }
    }

    $localPrograms = Join-Path $env:LOCALAPPDATA "Programs"
    foreach ($sub in @("Inno Setup 6", "Inno Setup 6 (x86)")) {
        $p = Join-Path (Join-Path $localPrograms $sub) "ISCC.exe"
        if (Test-Path -LiteralPath $p) { return $p }
    }

    return $null
}

function Copy-DirWithRobocopy {
    param([string]$Source, [string]$Destination)
    if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
    New-Item -ItemType Directory -Path $Destination | Out-Null
    & robocopy $Source $Destination /E /COPY:DAT /DCOPY:DAT /R:8 /W:2 /NFL /NDL /NJH /NJS | Out-Null
    $rc = $LASTEXITCODE
    if ($rc -gt 7) { throw "robocopy が終了コード $rc で失敗しました（$Source -> $Destination）。" }
}

New-Item -ItemType Directory -Force -Path "dist\release" | Out-Null
New-Item -ItemType Directory -Force -Path "dist\installer" | Out-Null

Write-Host "== uv sync (pack) ==" -ForegroundColor Cyan
uv sync --extra pack

Write-Host "== PyInstaller ==" -ForegroundColor Cyan
if (-not (Test-Path "fig\ico\app.ico")) {
    Write-Error "fig\ico\app.ico が見つかりません。アイコンを配置してから再実行してください。"
}
uv run pyinstaller packaging\fluxel.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller が終了コード $LASTEXITCODE で失敗しました。"
    exit $LASTEXITCODE
}

if (-not (Test-Path "dist\Fluxel\Fluxel.exe")) {
    Write-Error "dist\Fluxel\Fluxel.exe が見つかりません。PyInstaller に失敗した可能性があります。"
    exit 1
}

# --- 主成果物: Inno インストーラ + 配布用 ZIP ---
if ($env:FLUXEL_SKIP_INNO -eq "1") {
    Write-Warning "FLUXEL_SKIP_INNO=1 のため Inno Setup をスキップしました（配布用インストーラは未作成）。"
} else {
    Write-Host "== Inno Setup（配布用インストーラ） ==" -ForegroundColor Cyan
    $isccExe = Find-InnoISCC
    if (-not $isccExe) {
        Write-Error @'
ISCC.exe（Inno Setup コンパイラ）が見つかりません。配布の主成果物はインストーラのため、インストールしてから再実行してください。

例: winget install --id JRSoftware.InnoSetup -e --source winget

Inno なしで PyInstaller までだけ進めたい場合: 環境変数 FLUXEL_SKIP_INNO=1 を設定してください。
'@
        exit 1
    }
    Write-Host "Using $isccExe" -ForegroundColor Green
    & $isccExe `
        "/DMyAppVersion=$InstallerVersion" `
        "/DMyAppVersionDisplay=$ReleaseVersion" `
        "/DMyAppFileVersion=$FileVersion" `
        "$(Join-Path $PSScriptRoot 'fluxel.iss')"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup が終了コード $LASTEXITCODE で失敗しました。"
        exit $LASTEXITCODE
    }
    $setup = Get-ChildItem "dist\installer\Fluxel_Setup_*.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $setup) {
        Write-Error "dist\installer\ に Fluxel_Setup_*.exe が見つかりません。fluxel.iss の OutputDir / ファイル名を確認してください。"
        exit 1
    }
    $installerZip = Join-Path (Resolve-Path "dist\release") "Fluxel_Setup_${ReleaseVersion}_installer.zip"
    if (Test-Path $installerZip) { Remove-Item $installerZip -Force }
    Compress-Archive -Path $setup.FullName -DestinationPath $installerZip -CompressionLevel Optimal
    Write-Host "インストーラ EXE: $($setup.FullName)" -ForegroundColor Green
    Write-Host ("インストーラ EXE サイズ: {0:N1} MB" -f ($setup.Length / 1MB)) -ForegroundColor Green
    Write-Host "配布用 ZIP（推奨）: $(Resolve-Path $installerZip)" -ForegroundColor Green
}

# --- 任意: ポータブル ZIP ---
if ($env:FLUXEL_PORTABLE_ZIP -eq "1") {
    Write-Host "== 任意: ポータブル ZIP ==" -ForegroundColor Cyan
    $portableZip = "dist\release\Fluxel_portable_$ReleaseVersion.zip"
    if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
    $stage = "dist\release\_portable_zip_stage"
    Start-Sleep -Seconds 2
    $attempts = 6
    for ($a = 1; $a -le $attempts; $a++) {
        try {
            Copy-DirWithRobocopy -Source "dist\Fluxel" -Destination $stage
            Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $portableZip -CompressionLevel Optimal -ErrorAction Stop
            break
        } catch {
            if ($a -eq $attempts) { throw $_ }
            Write-Warning "ZIP 化リトライ $a/$attempts : $_"
            Start-Sleep -Seconds 5
        } finally {
            if (Test-Path $stage) { Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }
    $fullPortable = (Resolve-Path $portableZip).Path
    Write-Host "ポータブル ZIP: $fullPortable" -ForegroundColor Green
    Write-Host ("サイズ: {0:N1} MB" -f ((Get-Item $fullPortable).Length / 1MB)) -ForegroundColor Green
}

Write-Host ""
Write-Host "完了。配布は dist\release\ のインストーラ ZIP（または dist\installer\ の EXE）を主に使ってください。" -ForegroundColor Green
