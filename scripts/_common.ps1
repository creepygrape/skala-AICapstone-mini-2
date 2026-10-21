# Dot-sourced by run_backend.ps1 / run_frontend.ps1 (Windows PowerShell 5.1+ or pwsh).

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $value = $Matches[2]
            if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            Set-Item -Path "Env:$($Matches[1])" -Value $value
        }
    }
}

# Stop whatever listens on the port. Windows has no SIGTERM, so Stop-Process is forceful.
function Stop-PortListener([int]$Port) {
    $owners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        $name = (Get-Process -Id $id -ErrorAction SilentlyContinue).ProcessName
        Write-Host "Port $Port is in use: stopping PID $id ($name)"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    if ($owners) { Start-Sleep -Milliseconds 500 }
}
