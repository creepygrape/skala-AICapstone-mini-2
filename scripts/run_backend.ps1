# Start the Agent API on Windows: scripts\run_backend.ps1 [ollama|openai] [-Yes]
#   ollama (default) - local development, no billing
#   openai           - demo/submission, billed per request (asks y/N unless -Yes)
# Reads .env if present (Uvicorn itself does not). Port 8000 is freed first.
param([string]$Backend = '', [switch]$Yes)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
. "$PSScriptRoot\_common.ps1"

Import-DotEnv '.env'
if (-not $Backend) { $Backend = if ($env:WISH_LLM_BACKEND) { $env:WISH_LLM_BACKEND } else { 'ollama' } }
$env:WISH_LLM_BACKEND = $Backend
$env:WISH_AGENT_ENABLED = '1'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'
$env:PYTHONUTF8 = '1'

$python = '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw ".venv not found. Run: py -3.11 -m venv .venv; $python -m pip install -r backend\requirements.txt" }

switch ($Backend) {
    'ollama' {
        $fast = if ($env:WISH_OLLAMA_FAST_MODEL) { $env:WISH_OLLAMA_FAST_MODEL } elseif ($env:WISH_LLM_MODEL) { $env:WISH_LLM_MODEL } else { 'qwen3:8b' }
        Write-Host "LLM: ollama fast=$fast"
    }
    'openai' {
        if (-not $env:OPENAI_API_KEY -or $env:OPENAI_API_KEY -eq 'sk-...') {
            throw 'OPENAI_API_KEY is empty. Put your key in .env (see .env.example).'
        }
        $fastModel = if ($env:OPENAI_FAST_MODEL) { $env:OPENAI_FAST_MODEL } else { 'gpt-4o-mini' }
        $qualityModel = if ($env:OPENAI_QUALITY_MODEL) { $env:OPENAI_QUALITY_MODEL } else { 'gpt-4o' }
        Write-Host "LLM: openai fast=$fastModel quality=$qualityModel"
        Write-Host 'WARNING: every search calls the OpenAI API and is billed to your account.'
        Write-Host '         The question and up to 3 candidate subtitle excerpts (20s context) are sent to OpenAI.'
        if (-not $Yes) {
            $answer = Read-Host 'Continue? [y/N]'
            if ($answer -notmatch '^(y|yes)$') { Write-Host 'Aborted.'; exit 1 }
        }
    }
    default { throw "unknown backend '$Backend' (use ollama or openai)." }
}

Stop-PortListener 8000
& $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
exit $LASTEXITCODE
