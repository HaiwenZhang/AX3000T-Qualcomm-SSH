$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'resolve-python.ps1')
    $pythonPath = Resolve-ToolkitPython
    $program = Join-Path (Split-Path -Parent $PSScriptRoot) 'tests\test_offline.py'
    & $pythonPath -B $program
    exit $LASTEXITCODE
} catch {
    Write-Host ('STOP: ' + $_.Exception.Message)
    exit 1
}
