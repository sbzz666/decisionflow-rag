$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Python environment missing. Follow README installation instructions.'
}
if (-not (Test-Path -LiteralPath 'frontend/dist/index.html')) {
    Push-Location frontend
    try {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    } finally { Pop-Location }
}
Write-Host 'DecisionFlow: http://127.0.0.1:8765'
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8765
