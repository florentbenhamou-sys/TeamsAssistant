# Architecture technique

## Vue d'ensemble

```
            ┌──────────────────────── ui/ (PySide6) ────────────────────────┐
            │ Accueil · Nouvelle session · Session en cours · Transcription │
            │ Compte rendu · Historique · Paramètres   + bandeau REC permanent │
            └───────────────────────────────┬───────────────────────────────┘
                                            │ appelle uniquement
            ┌───────────────────────── services/ ───────────────────────────┐
            │ SessionService · TranscriptionService · SummaryService · M365  │
            └──────┬──────────────┬───────────────┬───────────────┬─────────┘
                   │              │               │               │
             audio/          transcription/    summary/          m365/
        CaptureBackend ⟂    SpeechEngine ⟂   SummaryGenerator ⟂  GraphClient
        (PyAudioWPatch,     (faster-whisper)  (local, Claude)    (MSAL + requests)
         soundcard)                │
                                   │
                         storage/ (SQLite, dépôts)   exports.py   secret_store.py
```

`⟂` = interface (`typing.Protocol`) : chaque implémentation est remplaçable, et les tests utilisent
des doublures (backend audio piloté, moteur factice, HTTP simulé).

`app_context.py` est le seul endroit qui assemble les dépendances.

## Flux d'une session

1. **Nouvelle session** : titre, réunion Outlook éventuelle, choix des périphériques, case de
   confirmation des autorisations (obligatoire, non pré-cochée).
2. **Capture** : `CaptureSession` ouvre toutes les sources, puis démarre leurs horloges ensemble.
   Chaque source → un WAV PCM 16 bits incrémental (`recordings/<session>/system.wav`, `microphone.wav`).
   Les silences loopback (aucune trame livrée par Windows) sont comblés d'après l'horloge système.
3. **Arrêt** : chaque fichier est relu et analysé ; la session n'est marquée « enregistrée » que si
   au moins un fichier contient réellement du signal.
4. **Transcription** : décodage 16 kHz, découpage en tronçons d'~5 min aux points les plus calmes,
   faster-whisper (VAD + horodatage par mot), persistance **par tronçon** → reprise possible.
   Fusion chronologique des sources, suppression de l'écho micro, signalement des passages douteux.
5. **Compte rendu** : générateur local (extraction par règles) ou Claude (option explicite) →
   structure commune avec, pour chaque élément, nature (fait / interprétation / extrait) et
   références aux segments.
6. **Validation** : corrections dans l'écran E ; toute modification annule la validation.

## Modèle de données (SQLite, schéma v1)

| Table | Rôle |
|---|---|
| `meeting_session` | Réunion (UUID), statut, horaires, lien Outlook/Teams, date de confirmation des autorisations |
| `audio_file` | Fichiers audio ; `owned=1` = temporaire créé par l'appli (supprimable), `0` = importé |
| `transcript` | Transcription (locale ou officielle), moteur, modèle, options, statut, avertissements |
| `transcript_chunk` | Tronçons terminés (reprise) |
| `transcript_segment` | Segments horodatés, source, libellé d'intervenant, texte, **texte d'origine** si corrigé |
| `participant` | Participants connus, identité confirmée / incertaine, origine |
| `meeting_summary` | Compte rendu (JSON structuré), générateur, validation |
| `action_item` | Actions extraites (responsable/échéance seulement si explicites), références |
| `application_settings` | Paramètres (aucun secret) |

Clés étrangères `ON DELETE CASCADE` : supprimer une session supprime tout ce qui en dépend.
Toutes les requêtes sont paramétrées.

## Sécurité et confidentialité

- Données dans `%LOCALAPPDATA%\TeamsAssistant\data`, **hors OneDrive**.
- Secrets : Gestionnaire d'identification Windows (`keyring`) ; jetons MSAL chiffrés DPAPI.
- Journaux : filtre de masquage (Bearer, JWT, clés, mots de passe) ; le code ne journalise jamais de
  transcription. Testé (`tests/test_logging.py`).
- Aucun envoi cloud sans : option activée + clé enregistrée + confirmation à chaque génération.

## Évolution vers une application multi-utilisateur

| Besoin | Évolution proposée |
|---|---|
| **API backend** | Exposer `services/` via FastAPI ; l'UI PySide6 (ou une UI web) devient client HTTP. Les services n'ont aucune dépendance Qt : la migration est directe. |
| **PostgreSQL** | Remplacer `storage/db.py` + `Database` par SQLAlchemy/psycopg ; le schéma (UUID texte, types simples, cascades) est portable. Ajouter Alembic pour les migrations. |
| **Plusieurs utilisateurs** | Colonne `owner_id` sur `meeting_session` (et héritage par cascade), filtrage systématique dans les dépôts. |
| **Authentification centralisée** | Entra ID (OIDC) côté API ; la capture reste sur le poste (agent local) et téléverse l'audio ou la transcription. |
| **Droits d'accès** | Rôles (propriétaire, lecteur, équipe commerciale) + partage par session ; journal d'audit. |
| **Stockage documentaire sécurisé** | Audio et exports dans un stockage objet chiffré (Azure Blob + clés gérées) ou SharePoint via Graph ; durées de conservation par politique. |
| **Transcription serveur** | Le `SpeechEngine` peut devenir un worker GPU (file de tâches) ; la reprise par tronçon est déjà en place. |
| **Lien avec le suivi commercial** | `meeting_session` porte déjà `outlook_event_id` ; ajouter `account_id`/`opportunity_id` et exporter `action_item` vers l'application de prospection. |

Rien de cela n'est implémenté dans le prototype (volontairement mono-poste).
