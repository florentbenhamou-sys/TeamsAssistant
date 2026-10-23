@echo off
rem Double-clic : lance TeamsAssistant (prépare l'environnement au premier lancement).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1"
