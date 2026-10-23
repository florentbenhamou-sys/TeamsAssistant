# TeamsAssistant

Assistant personnel **local** de transcription et de compte rendu de réunions Microsoft Teams
(Teams Desktop ou navigateur), pour Windows. Pensé pour les réunions organisées par d'autres
entreprises, où le transcript officiel n'est pas accessible.

> ⚠️ **Enregistrer une réunion suppose d'en avoir le droit et d'en avoir informé les participants.**
> L'application ne démarre jamais une capture d'elle-même, exige une confirmation à chaque session et
> affiche en permanence un bandeau d'enregistrement.

**Statut : prototype.** Ce qui est vérifié, partiel ou non testé est détaillé dans
[`PLAN.md`](PLAN.md#bilan-des-fonctionnalités).

## Fonctionnement

1. **Capture** du son de la réunion diffusé par le PC (WASAPI loopback) et, en option, du micro, dans
   des fichiers séparés — ou **import** d'un fichier audio/vidéo existant.
2. **Transcription locale** en français avec faster-whisper (aucun envoi d'audio), horodatée, par
   tronçons avec reprise, passages douteux signalés.
3. **Compte rendu structuré** (décisions, questions, risques, engagements, actions…) : générateur local
   sans IA par défaut, IA cloud Claude en option explicite.
4. **Correction, validation, export** (TXT, Markdown, JSON, DOCX), **historique** avec recherche,
   **suppression** contrôlée.
5. **Microsoft 365** (facultatif) : réunions Outlook à venir et récupération du transcript officiel
   Teams lorsque l'organisation l'autorise.

## Installation

Pré-requis : Windows 10/11, Python 3.12+ (testé avec 3.14.4, commande `py`), ~2 Go d'espace disque
(environnement + modèle « small »).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

L'environnement Python est créé dans `%LOCALAPPDATA%\TeamsAssistant\venv` et les données dans
`%LOCALAPPDATA%\TeamsAssistant\data` : **hors OneDrive**, volontairement (taille, confidentialité).
Au premier usage de la transcription, le modèle est téléchargé depuis Hugging Face (gratuit, ~480 Mo
pour le profil « rapide »).

## Utilisation

Double-clic sur **`TeamsAssistant.bat`** (ou `scripts\run.ps1`).

| Écran | Rôle |
|---|---|
| Accueil | État, réunions Outlook, dernières transcriptions et comptes rendus |
| Nouvelle session | Titre, réunion Outlook, sortie audio de Teams, micro (optionnel), confirmation des autorisations |
| Session en cours | Durée, état réel, vumètres, alertes, Suspendre / Reprendre / Arrêter |
| Transcription | Lancer / reprendre, texte horodaté éditable, recherche, transcript Teams officiel, exports |
| Compte rendu | Générer, corriger, voir le passage source, valider, exporter Markdown / DOCX |
| Historique | Rechercher, ouvrir, renommer, exporter, supprimer |
| Paramètres | Périphériques, modèle, IA, Microsoft 365, conservation, confidentialité |

Conseil : choisissez comme « Son de la réunion » la sortie indiquée dans Teams > Paramètres >
Périphériques. En cas de doute : `scripts\diag.ps1 probe` pendant que la réunion est audible.

## Outils en ligne de commande

```powershell
scripts\diag.ps1 list                         # périphériques audio
scripts\diag.ps1 record --seconds 5 --tone    # test de capture avec bip
& "$env:LOCALAPPDATA\TeamsAssistant\venv\Scripts\python.exe" -m teams_assistant.transcription.cli fichier.wav
& "$env:LOCALAPPDATA\TeamsAssistant\venv\Scripts\python.exe" scripts\demo_pipeline.py   # exemple complet
```

## Tests

```powershell
$py = "$env:LOCALAPPDATA\TeamsAssistant\venv\Scripts\python.exe"
& $py -m pytest              # 61 tests automatisés (sans matériel ni réseau)
& $py -m pytest -m hardware  # capture réelle (joue un bip discret)
& $py -m pytest -m model     # transcription réelle de l'échantillon (modèle small)
& $py -m mypy src            # typage strict
```

## Documentation

- [`PLAN.md`](PLAN.md) — phases, décisions, risques, **bilan des fonctionnalités**
- [`docs/architecture.md`](docs/architecture.md) — modules, données, sécurité, évolution multi-utilisateur
- [`docs/audio-diagnostic.md`](docs/audio-diagnostic.md) — capture, mesures réelles, dépannage
- [`docs/microsoft-graph.md`](docs/microsoft-graph.md) — inscription Entra ID, permissions, limites
- [`docs/compte-rendu.md`](docs/compte-rendu.md) — modèle de compte rendu, générateurs, coûts
- [`docs/test-protocol.md`](docs/test-protocol.md) — protocole de test manuel
- [`samples/meeting_demo/`](samples/meeting_demo/) — réunion **synthétique** (voix de synthèse,
  sociétés fictives) avec vérité terrain, transcription et compte rendu d'exemple
