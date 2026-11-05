function Resolve-ToolkitPython {
    $packageRoot = Split-Path -Parent $PSScriptRoot
    $candidates = @()
    if ($env:AX3000T_PYTHON) {
        $candidates = @($env:AX3000T_PYTHON)
    } else {
        $candidates += Join-Path $packageRoot '.venv\Scripts\python.exe'
        if ($env:VIRTUAL_ENV) {
            $candidates += Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        }
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            try {
                $installed = & $launcher.Source -0p 2>$null
                $interpreters = foreach ($line in $installed) {
                    if ($line -match '(?<Path>[A-Za-z]:\\.+python(?:w)?\.exe)\s*$') {
                        $path = $Matches.Path
                        $preferred = $line -match '(?:-V:3\.|-3\.)13(?:\D|$)'
                        [PSCustomObject]@{ Path = $path; Preferred = $preferred }
                    }
                }
                foreach ($interpreter in ($interpreters | Sort-Object @{Expression={if ($_.Preferred) {0} else {1}}})) {
                    $candidates += $interpreter.Path
                }
            } catch { }
        }
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*\WindowsApps\*') {
            $candidates += $command.Source
        }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $path = & $candidate -c 'import struct,sys; assert sys.version_info >= (3,10) and struct.calcsize(chr(80))==8; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $path) {
                return ($path | Select-Object -Last 1).Trim()
            }
        } catch { }
    }
    throw 'Install Python 3.13 x64 yourself, then install requirements.txt. See README.md. Optional: AX3000T_PYTHON specifies an interpreter.'
}
