param([switch]$TestBuild)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements-build.txt first.' }
    if (-not (Test-Path -LiteralPath 'dist/MemuMusic.exe')) { throw 'Build dist/MemuMusic.exe first.' }
    $version = & $python -c 'from memumusic import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*$') { throw 'Invalid application version.' }
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $compiler = if ($command) { $command.Source } else { Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe' }
    if (-not (Test-Path -LiteralPath $compiler)) { throw 'Inno Setup 6 is required to build the installer.' }
    $argsForCompiler = @("/DAppVersion=$version")
    if ($TestBuild) { $argsForCompiler += '/DTestBuild=1' }
    $argsForCompiler += 'installer/MemuMusic.iss'
    & $compiler @argsForCompiler
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    $name = if ($TestBuild) { 'MemuMusic-Setup-test.exe' } else { 'MemuMusic-Setup.exe' }
    $output = if ($TestBuild) { 'build/test-installer' } else { 'dist' }
    $setup = Join-Path $PSScriptRoot "$output/$name"
    $hash = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText("$setup.sha256", "$hash  $name`n", [Text.Encoding]::ASCII)
    Write-Host "Ready: $setup"
} finally { Pop-Location }
