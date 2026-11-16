# Build a Windows desktop installer with its matching Python and Rust sources.
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$frontend = Join-Path $root 'frontend'
$desktop = Get-Content (Join-Path $frontend 'src-tauri/tauri.conf.json') -Raw |
    ConvertFrom-Json
$resourceName = "command-center-backend-$($desktop.version)"
$stage = Join-Path ([IO.Path]::GetTempPath()) ("openjarvis-bundle-" + [guid]::NewGuid())
$archive = Join-Path $stage 'backend.tar'
$backend = Join-Path $stage $resourceName
$overlay = Join-Path $stage 'tauri.bundle.json'

Push-Location $root
try {
    git diff --quiet HEAD -- src rust pyproject.toml uv.lock README.md LICENSE configs scripts/install deploy/windows frontend/src frontend/src-tauri/src frontend/src-tauri/tauri.conf.json frontend/src-tauri/Cargo.toml frontend/package.json
    if ($LASTEXITCODE -ne 0) { throw 'Commit desktop and backend changes before building.' }
    $untracked = git ls-files --others --exclude-standard -- src rust frontend/src frontend/src-tauri/src
    if ($LASTEXITCODE -ne 0 -or $untracked) {
        throw 'Commit new desktop and backend files before building.'
    }
    New-Item -ItemType Directory -Path $backend | Out-Null
    git archive --format=tar --output=$archive HEAD -- src rust pyproject.toml uv.lock README.md LICENSE configs scripts/install deploy/windows
    if ($LASTEXITCODE -ne 0) { throw 'Could not archive the backend source.' }
    tar.exe -xf $archive -C $backend
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage the backend source.' }
    $resources = @{}
    $resources[$backend] = "$resourceName/"
    @{ bundle = @{ resources = $resources } } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $overlay -Encoding utf8

    npm --prefix $frontend run tauri -- build --bundles nsis --config $overlay
    if ($LASTEXITCODE -ne 0) { throw 'The Windows bundler failed.' }
} finally {
    Pop-Location
    if (Test-Path -LiteralPath $stage) {
        $resolvedStage = (Resolve-Path -LiteralPath $stage).Path
        if ($resolvedStage -eq $stage -and
            [IO.Path]::GetFileName($resolvedStage) -match '^openjarvis-bundle-[a-f0-9-]+$') {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }
}
