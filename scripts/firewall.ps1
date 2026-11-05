param(
    [ValidateSet('Add','Remove')][string]$Action = 'Add',
    [string]$RouterIp = '192.168.31.1',
    [ValidateRange(1024,65535)][int]$Port = 8000
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Right-click the firewall launcher and select Run as administrator.'
}
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($RouterIp, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'RouterIp must be a private numeric IPv4 address.'
}
$octets = $parsedAddress.GetAddressBytes()
if (-not ($octets[0] -eq 10 -or
    ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31) -or
    ($octets[0] -eq 192 -and $octets[1] -eq 168))) {
    throw 'Only private LAN IPv4 addresses are supported.'
}
$routerAddress = $parsedAddress.ToString()
. (Join-Path $PSScriptRoot 'resolve-python.ps1')
$pythonPath = Resolve-ToolkitPython
$sha = [Security.Cryptography.SHA256]::Create()
try {
    $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($pythonPath.ToLowerInvariant()))
    $suffix = ([BitConverter]::ToString($digest)).Replace('-','').Substring(0,12)
} finally { $sha.Dispose() }
$ruleName = 'AX3000T-Qualcomm-SSH-' + $suffix + '-' + $routerAddress.Replace('.','-') + '-' + $Port
$existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($Action -eq 'Remove') {
    if ($existingRule) { $existingRule | Remove-NetFirewallRule }
    Write-Host 'Temporary rule removed (or already absent).'
} elseif ($existingRule) {
    Write-Host 'The rule for this folder, router and port already exists.'
} else {
    New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow `
        -Program $pythonPath -Protocol TCP -LocalPort $Port -RemoteAddress $routerAddress `
        -Profile Any | Out-Null
    Write-Host "Allowed only $routerAddress to contact $pythonPath on TCP/$Port."
}
