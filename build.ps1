$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
    }
    & '.venv/Scripts/python.exe' -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & '.venv/Scripts/python.exe' -m PyInstaller --noconfirm MemuMusic.spec
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    $hash = (Get-FileHash 'dist/MemuMusic.exe' -Algorithm SHA256).Hash.ToLower()
    [IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dist/MemuMusic.exe.sha256'), "$hash  MemuMusic.exe`n")
    Write-Host 'Ready: dist/MemuMusic.exe'
} finally { Pop-Location }
