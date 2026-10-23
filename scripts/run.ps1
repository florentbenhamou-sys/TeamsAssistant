# Lance l'application TeamsAssistant.
$venvPy = "$env:LOCALAPPDATA\TeamsAssistant\venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Environnement absent : lancement de la préparation (scripts\setup.ps1)..." -ForegroundColor Yellow
    & "$PSScriptRoot\setup.ps1"
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
Start-Process -FilePath $venvPy -ArgumentList "-m", "teams_assistant"
