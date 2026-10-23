# PLAN — TeamsAssistant (prototype)

Assistant personnel local pour transcrire des réunions Microsoft Teams (Desktop ou navigateur),
en particulier celles organisées par des entreprises tierces sans transcript officiel accessible.

Légende : ✅ fait et vérifié · 🟡 code écrit, vérification partielle · ⏳ à faire

---

## Phase 1 — Analyse de l'environnement ✅ (23/10/2026)

### Poste inspecté (mesures réelles)

| Élément | Constat |
|---|---|
| OS | Windows 11 Entreprise, build 26200 |
| Python | 3.14.4 seul installé (Python Install Manager, commande `py`) |
| CPU | Intel i7-11800H, 8 cœurs / 16 threads |
| RAM | 31,7 Go |
| GPU | NVIDIA T600 Laptop 4 Go (pilote 581.95) + Intel UHD. CTranslate2 voit le GPU, mais **cuBLAS 12 / cuDNN 9 absents** → transcription GPU non disponible sans installation supplémentaire |
| Disque | C: 21,8 Go libres · D: 613 Go libres |
| ffmpeg | 8.1.1 présent (winget) — non requis (faster-whisper décode via PyAV) |
| git | 2.53 ; `gh` absent (le dépôt est synchronisé par git + Git Credential Manager) |
| Ollama / LLM local | absent |
| Audio (WASAPI) | Sorties : casque Jabra Evolve2 65 (44,1 kHz), haut-parleurs Realtek, écran PL2474H (HDMI). Entrées : micro Jabra (16 kHz mono), réseau de micros Realtek (48 kHz) |

### Compatibilité des bibliothèques sous Python 3.14 (installations réelles, wheels uniquement)

Toutes installées sans compilation : `PyAudioWPatch 0.2.12.9`, `soundcard 0.4.6`, `sounddevice 0.5.6`,
`faster-whisper 1.2.1` (`ctranslate2 4.8.3`, `av 19`), `PySide6-Essentials 6.12`, `msal 1.39`,
`keyring 25.7`, `python-docx 1.2`, `numpy 2.5`, `pytest 9.1`.

### Choix techniques

| Besoin | Choix | Justification |
|---|---|---|
| Langage | Python 3.14 (compatible ≥ 3.12) | Écosystème audio/IA, déjà installé |
| Interface | **PySide6** (Qt 6) | Application native Windows, threads + signaux pour le vumètre et la progression, pas de serveur web à gérer. Une alternative web (Flask + navigateur) n'apporterait rien ici : la capture audio doit de toute façon tourner localement |
| Capture | **PyAudioWPatch** (WASAPI loopback) en principal, **soundcard** en repli | Les deux testés en réel sur le poste. PyAudioWPatch : meilleur alignement temporel. soundcard : sans PortAudio, utile si PyAudio échoue |
| Format | WAV PCM 16 bits, fréquence native du périphérique, un fichier par source | Lisible partout, écriture incrémentale résistante aux arrêts brutaux, pas de rééchantillonnage pendant la capture |
| Transcription | **faster-whisper** (CPU int8 par défaut) | Local, français performant, horodatages, VAD intégré. GPU possible plus tard (DLL CUDA à ajouter) |
| Stockage | **SQLite** (stdlib) | Mono-utilisateur, zéro installation, migrable vers PostgreSQL |
| Compte rendu | Générateur **local** (sans LLM, extraction prudente) par défaut + **Claude API** optionnel, désactivé par défaut | Rien ne quitte le poste sans action explicite. Ollama possible ultérieurement |
| Microsoft 365 | **MSAL** (client public, connexion interactive navigateur) + cache de jetons chiffré DPAPI | Pas de mot de passe dans l'application, pas de secret client |
| Secrets | Gestionnaire d'identification Windows (`keyring`) | Jamais en clair dans un fichier |

### Emplacements

- Code : `00-Claude\12-TeamsAssistant` (dépôt GitHub `florentbenhamou-sys/TeamsAssistant`).
- Environnement Python : `%LOCALAPPDATA%\TeamsAssistant\venv` — **hors OneDrive** (des milliers de fichiers à ne pas synchroniser).
- Données (base, audio temporaire, exports, journaux, modèles) : `%LOCALAPPDATA%\TeamsAssistant\data`
  — **hors OneDrive volontairement** : les enregistrements de réunion sont confidentiels. Modifiable via
  `TEAMS_ASSISTANT_DATA_DIR`.

### Architecture modulaire

```
src/teams_assistant/
  audio/           capture WASAPI (backends interchangeables), recorder, diagnostic CLI
  transcription/   moteur (interface) + implémentation faster-whisper, découpage, reprise
  summary/         générateurs de compte rendu (interface) : local, cloud optionnel
  m365/            authentification MSAL, calendrier, transcripts officiels (Graph)
  storage/         schéma SQLite, dépôts (repositories)
  services/        logique métier (sessions, conservation, suppression)
  exports/         TXT, Markdown, JSON, DOCX
  ui/              écrans PySide6 (A à G)
  config.py, logging_setup.py
```

Chaque domaine expose une interface (`typing.Protocol`) : l'UI ne dépend que des services,
les services ne dépendent que des interfaces. Voir `docs/architecture.md`.

### Risques et inconnues

| # | Risque | Niveau | Traitement |
|---|---|---|---|
| R1 | Loopback WASAPI : **aucune trame livrée pendant le silence** (constaté : 0 trame sur 3 s) | Élevé → maîtrisé | Comblement par silence calé sur l'horloge système (testé) |
| R2 | Teams peut utiliser une autre sortie que celle par défaut de Windows | Moyen | Sélection explicite + commande `probe` qui repère la sortie active |
| R3 | Casque sans fil : disparition du périphérique en cours de séance (constaté pendant les tests : le Jabra a disparu de la liste, index renumérotés) | Moyen | Résolution par nom, alerte « flux interrompu », fichier conservé jusqu'au point de coupure |
| R4 | Mode exclusif d'une autre application bloquant le périphérique | Faible | Message d'erreur avec consigne |
| R5 | Transcription CPU lente sur modèles larges | Moyen | Profils (rapide / équilibré / précis), traitement par segments avec reprise |
| R6 | Transcripts officiels Graph : accès limité (réunions de votre tenant, consentement admin requis pour `OnlineMeetingTranscript.Read.All`) ; **réunions externes probablement inaccessibles** | Élevé (fonctionnel) | La transcription locale reste la voie principale ; Graph est un bonus |
| R7 | Identification des intervenants | Moyen | Séparation par source (micro local / son distant) uniquement ; pas de diarisation automatique fiable sans dépendances lourdes (pyannote + jeton HF) ; libellés neutres |
| R8 | Qualité de l'audio compressé Teams | Faible | Whisper est robuste ; à mesurer en réunion réelle |
| R9 | Aspect légal : information des participants | — | Rappel obligatoire avant chaque capture, indicateur permanent, aucun démarrage automatique |

---

## Phase 2 — Preuve de faisabilité audio ✅ (sur le matériel disponible)

Résultats détaillés et limites : [`docs/audio-diagnostic.md`](docs/audio-diagnostic.md).

- ✅ Énumération WASAPI (entrées + loopbacks) avec deux backends.
- ✅ Capture loopback réelle validée (casque Jabra et haut-parleurs Realtek, bip de test) sur les deux backends.
- ✅ Détection honnête de l'absence de signal (capture silencieuse → « NON VALIDÉE »).
- ✅ Pause / reprise réelles, fichiers micro et système alignés sur la même origine de temps.
- 🟡 Micro : flux ouvert et données reçues (bruit de fond mesuré), **mais aucun test avec voix humaine** (nécessite votre intervention).
- ⏳ Test pendant une vraie réunion Teams Desktop / navigateur : à réaliser par vous (protocole dans `docs/test-protocol.md`).
- ⏳ Débranchement en cours de capture : couvert par test automatisé (simulation), pas testé physiquement.

## Phase 3 — Prototype de transcription ✅

- faster-whisper local, profils rapide (small) / équilibré (medium) / précis (large-v3-turbo), CPU int8.
- Décodeur PyAV propre : `faster_whisper.decode_audio` 1.2.1 est **incompatible avec PyAV 19**
  (option `metadata_errors` supprimée) — constaté sur le poste.
- Découpage en tronçons de ~5 min aux points les plus calmes, persistance par tronçon, **reprise** testée.
- Horodatage par mot (bornes de segments nettement plus justes, mesuré contre la vérité terrain).
- Fusion micro / son du PC, suppression de l'écho, passages douteux signalés.
- **Mesure réelle** (échantillon synthétique 82,5 s, profil rapide, CPU i7-11800H) : 15 à 40 s de
  traitement selon la mise en cache (2 à 5× plus rapide que le temps réel), langue détectée « fr » à
  100 %, mots-clés et chronologie corrects, un nom propre déformé (« Nordia Logistique »).
- Profils « équilibré » et « précis » : **non mesurés** (modèles de 1,5 Go non téléchargés).
- GPU : non utilisé (cuBLAS/cuDNN absents) ; option présente mais **non testée**.

## Phase 4 — Interface et stockage ✅ (hors tests en réunion réelle)

- SQLite (9 tables, cascades, requêtes paramétrées), services métier, exports TXT/MD/JSON/DOCX.
- Interface PySide6, 7 écrans, bandeau d'enregistrement permanent (titre de fenêtre « ● REC »),
  fermeture impossible sans arrêter proprement la capture.
- Vérifié : parcours complet automatisé hors écran (capture simulée → transcription → correction →
  compte rendu → validation → suppression), rendu visuel de chaque écran, démarrage réel de
  l'application. Largeur minimale < 900 px (tablette 1024 px).

## Phase 5 — Comptes rendus ✅ (générateur local) / 🟡 (cloud)

- Structure commune en 13 rubriques, nature de chaque élément (fait / interprétation / extrait),
  références aux segments, édition, validation, actions extraites.
- Générateur local testé sur la vérité terrain. Générateur Claude : code et garde-fous testés,
  **aucun appel réel** (pas de clé API).

## Phase 6 — Microsoft 365 🟡 (code écrit, non validé)

- MSAL client public interactif, cache chiffré DPAPI, calendrier, recherche de réunion par
  `joinWebUrl`, transcripts (WebVTT), classification accessible / non accessible / refusé.
- Testé uniquement avec des réponses simulées. **Nécessite votre inscription d'application et un
  consentement administrateur** : voir `docs/microsoft-graph.md`.

## Phase 7 — Validation et documentation ✅

- 61 tests automatisés + 2 tests matériels + 1 test modèle : tous verts au 23/10/2026. mypy strict : OK.
- Documentation : README, architecture, diagnostic audio, Graph, compte rendu, protocole de test.

---

## Bilan des fonctionnalités

| Fonctionnalité | Statut | Preuve / reste à faire |
|---|---|---|
| Énumération et sélection des périphériques | ✅ Opérationnel | Testé sur le poste (2 backends) |
| Capture son du PC (loopback) | ✅ Opérationnel | Bip de test capturé (casque, haut-parleurs) |
| Capture micro | 🟡 Partiel | Flux reçu ; **voix réelle non testée** |
| Pause / reprise / arrêt, indicateur permanent | ✅ Opérationnel | Test matériel + test d'interface |
| Capture pendant une vraie réunion Teams (Desktop / navigateur) | ⏳ Non testé | Protocole §1–2 |
| Débranchement d'un périphérique en cours de capture | 🟡 Partiel | Simulé uniquement |
| Import de fichier audio/vidéo | ✅ Opérationnel | Tests automatisés |
| Transcription locale française horodatée | ✅ Opérationnel | Échantillon synthétique (voix de synthèse) |
| Qualité sur voix réelles / audio Teams compressé | ⏳ Non mesuré | À évaluer en réunion |
| Reprise d'une transcription interrompue | ✅ Opérationnel | Tests automatisés |
| Séparation des intervenants | 🟡 Partiel | Par source (micro / son du PC) uniquement ; pas de diarisation |
| Identification nominative | ❌ Non implémenté (volontaire) | Libellés neutres ; renommage manuel ; noms Teams si transcript officiel |
| Compte rendu local | ✅ Opérationnel | Extraction, pas de rédaction |
| Compte rendu IA cloud | 🟡 Non validé | Nécessite une clé API (payant) |
| Correction, validation, exports, historique, suppression | ✅ Opérationnel | Tests automatisés + interface |
| Conservation / purge de l'audio temporaire | ✅ Opérationnel | Tests automatisés |
| Calendrier Outlook | 🟡 Non validé | Nécessite inscription Entra ID |
| Transcript officiel Teams | 🟡 Non validé | Consentement administrateur requis ; réunions externes a priori inaccessibles |
| Transcription GPU | ❌ Non testé | Installer cuBLAS 12 / cuDNN 9 |
| Lien avec l'application de suivi commercial | ❌ Non implémenté | Prévu (voir `docs/architecture.md`) |

---

## Journal des décisions

| Date | Décision |
|---|---|
| 23/10/2026 | D1 — Python 3.14 + venv hors OneDrive |
| 23/10/2026 | D2 — PyAudioWPatch principal, soundcard en repli (les deux validés en réel) |
| 23/10/2026 | D3 — Un WAV par source (pas de mixage en direct) ; mixage à la transcription |
| 23/10/2026 | D4 — Comblement des silences loopback par l'horloge système |
| 23/10/2026 | D5 — Données hors OneDrive par défaut (confidentialité) |
| 23/10/2026 | D6 — Ouverture de toutes les sources puis démarrage simultané (alignement micro/système) |
| 23/10/2026 | D7 — Décodeur PyAV maison (incompatibilité faster-whisper 1.2.1 / PyAV 19) |
| 23/10/2026 | D8 — Horodatage par mot activé (bornes de segments) |
| 23/10/2026 | D9 — Générateur de compte rendu local sans IA par défaut ; Claude (`claude-opus-5-5`) optionnel avec confirmation |
| 23/10/2026 | D10 — Graph en délégué uniquement, aucune permission application, cache DPAPI |
| 23/10/2026 | D11 — Pas de diarisation automatique (pyannote : dépendances lourdes, jeton HF) ; séparation par source |
