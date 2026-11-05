$ErrorActionPreference = 'Stop'
try {
    . (Join-Path $PSScriptRoot 'resolve-python.ps1')
    $pythonPath = Resolve-ToolkitPython
    $program = Join-Path (Split-Path -Parent $PSScriptRoot) 'app\offline_ssh.py'
    Write-Host "Python: $pythonPath"
    & $pythonPath -B $program @args
    exit $LASTEXITCODE
} catch {
    Write-Host ('STOP: ' + $_.Exception.Message)
    exit 1
}
