# Prépare l'environnement Python local (hors OneDrive) et installe les dépendances.
# Usage : scripts\setup.ps1 [-Extras all] [-VenvPath chemin]
param(
    [string]$Extras = "all",
    [string]$VenvPath = "$env:LOCALAPPDATA\TeamsAssistant\venv"
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Recherche d'un Python >= 3.12 via le lanceur py
$python = $null
foreach ($v in @("3.14", "3.13", "3.12")) {
    & py "-$v" -c "import sys" 2>$null
    if ($LASTEXITCODE -eq 0) { $python = $v; break }
}
if (-not $python) {
    Write-Host "Python 3.12+ introuvable. Installez-le depuis https://www.python.org/downloads/windows/" -ForegroundColor Red
    exit 1
}
Write-Host "Python $python détecté."

if (-not (Test-Path "$VenvPath\Scripts\python.exe")) {
    Write-Host "Création de l'environnement : $VenvPath"
    & py "-$python" -m venv $VenvPath
}
$venvPy = "$VenvPath\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -e "$ProjectRoot[$Extras]"
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de l'installation des dépendances." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Environnement prêt." -ForegroundColor Green
Write-Host "  Diagnostic audio : scripts\diag.ps1 list"
Write-Host "  Application      : scripts\run.ps1  (ou double-clic sur TeamsAssistant.bat)"
