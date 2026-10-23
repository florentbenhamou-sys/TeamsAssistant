# Lance le module de diagnostic audio. Exemple : scripts\diag.ps1 record --seconds 5 --tone
$venvPy = "$env:LOCALAPPDATA\TeamsAssistant\venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Host "Lancez d'abord scripts\setup.ps1" -ForegroundColor Red; exit 1 }
& $venvPy -m teams_assistant.audio.diagnostic @args
exit $LASTEXITCODE
