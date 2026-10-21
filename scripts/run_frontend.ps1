# Start the Vue dev server on :5173 (Windows). Open http://localhost:5173/ (not 127.0.0.1).
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_common.ps1"

if (-not (Test-Path frontend\node_modules)) { npm --prefix frontend ci }
Stop-PortListener 5173
Write-Host 'Frontend: http://localhost:5173/  (backend expected on http://127.0.0.1:8000)'
npm --prefix frontend run dev -- --port 5173 --strictPort
exit $LASTEXITCODE
