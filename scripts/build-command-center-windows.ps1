[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $OutputDirectory
)

$ErrorActionPreference = 'Stop'
$artifactRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$originalPath = $env:Path

function Invoke-ReleaseCommand {
    param([string] $Program, [string[]] $Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program exited with code $LASTEXITCODE."
    }
}

Push-Location $repo
try {
    $dirty = Invoke-ReleaseCommand git @('status', '--porcelain', '--untracked-files=all', '--', '.', ':(exclude)frontend/tsconfig.tsbuildinfo')
    if ($dirty) { throw 'Commit the source changes before building release artifacts.' }

    $commit = Invoke-ReleaseCommand git @('rev-parse', 'HEAD')
    $version = (Get-Content frontend/src-tauri/tauri.conf.json -Raw | ConvertFrom-Json).version
    if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Unsupported release version $version." }
    $frontendPackage = Get-Content frontend/package.json -Raw | ConvertFrom-Json
    $frontendLock = Get-Content frontend/package-lock.json -Raw | ConvertFrom-Json
    if ($frontendPackage.version -ne $version -or $frontendLock.version -ne $version) {
        throw 'Desktop and frontend versions must match.'
    }

    $cargoBin = Join-Path $env:USERPROFILE '.cargo/bin'
    if (Test-Path -LiteralPath $cargoBin) { $env:Path = "$cargoBin;$env:Path" }
    $stage = Join-Path ([IO.Path]::GetTempPath()) "openjarvis-bundle-$([guid]::NewGuid())"
    $resource = "command-center-backend-$version"
    $backend = Join-Path $stage $resource
    New-Item -ItemType Directory -Path $backend | Out-Null

    $tar = Join-Path $stage 'backend.tar'
    Invoke-ReleaseCommand git @('archive', '--format=tar', "--output=$tar", $commit, 'LICENSE', 'README.md', 'configs', 'deploy', 'pyproject.toml', 'rust', 'scripts', 'src', 'uv.lock')
    Invoke-ReleaseCommand tar @('-xf', $tar, '-C', $backend)
    $bundleConfig = Join-Path $stage 'tauri.bundle.json'
    @{ bundle = @{ resources = @{ $backend = "$resource/" } } } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $bundleConfig -Encoding utf8

    Push-Location frontend
    try {
        Invoke-ReleaseCommand npx @('--no-install', 'tauri', 'build', '--bundles', 'nsis', '--config', $bundleConfig)
    } finally {
        Pop-Location
    }

    if ((Invoke-ReleaseCommand git @('rev-parse', 'HEAD')) -ne $commit) {
        throw 'The checked-out commit changed during the build.'
    }
    $target = Join-Path $repo 'frontend/src-tauri/target/release'
    $app = Get-Item -LiteralPath (Join-Path $target 'openjarvis-desktop.exe')
    if ($app.VersionInfo.ProductVersion -notin @($version, "$version.0")) {
        throw 'The compiled Windows app version does not match the release.'
    }
    $manifest = Join-Path $target 'nsis/x64/installer.nsi'
    $backendPattern = [regex]::Escape($resource) + '.*pyproject\.toml'
    if (!(Select-String -LiteralPath $manifest -Pattern $backendPattern -Quiet)) {
        throw 'The version-matched backend is missing from the installer.'
    }

    $installerName = "OpenJarvis-Command-Center-v$version-x64-setup.exe"
    $templateName = "OpenJarvis-Command-Center-Template-v$version.zip"
    $release = Join-Path $artifactRoot "releases/v$version"
    $templates = Join-Path $artifactRoot 'templates'
    New-Item -ItemType Directory -Force -Path $release, $templates | Out-Null

    $stagedTemplate = Join-Path $stage $templateName
    Invoke-ReleaseCommand git @('archive', '--format=zip', '--prefix=OpenJarvis-Command-Center/', "--output=$stagedTemplate", $commit)
    Invoke-ReleaseCommand python @('-m', 'zipfile', '-t', $stagedTemplate)
    $template = Join-Path $templates $templateName
    $installer = Join-Path $release $installerName
    $builtInstaller = Join-Path $target "bundle/nsis/OpenJarvis_${version}_x64-setup.exe"
    Copy-Item -LiteralPath $stagedTemplate -Destination $template
    Copy-Item -LiteralPath $builtInstaller -Destination $installer
    foreach ($pair in @(@($builtInstaller, $installer), @($stagedTemplate, $template))) {
        $destination = Get-FileHash -LiteralPath $pair[1]
        if ((Get-FileHash -LiteralPath $pair[0]).Hash -ne $destination.Hash) {
            throw "Artifact copy failed checksum verification: $($pair[1])"
        }
        $destination
    }
} finally {
    $env:Path = $originalPath
    Pop-Location
}
