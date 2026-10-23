# Guide de configuration Microsoft Graph

> Statut : **code écrit et testé avec des réponses simulées, NON validé sur un tenant réel.**
> Aucun test n'a été réalisé avec votre compte : l'intégration ne doit pas être considérée comme
> opérationnelle avant le protocole « M365 » de [`test-protocol.md`](test-protocol.md).

L'intégration Microsoft 365 est **facultative**. Sans elle, la capture, la transcription locale et
les comptes rendus fonctionnent normalement.

## Ce que fait l'application

| Fonction | Requête Graph (lecture seule) | Permission déléguée | Consentement |
|---|---|---|---|
| Identifier l'utilisateur | `GET /me` (via MSAL) | `User.Read` | utilisateur |
| Réunions à venir | `GET /me/calendarView` | `Calendars.Read` | utilisateur (selon la politique du tenant) |
| Retrouver la réunion Teams | `GET /me/onlineMeetings?$filter=JoinWebUrl eq '…'` | `OnlineMeetings.Read` | utilisateur (selon la politique) |
| Lister / lire les transcripts | `GET /me/onlineMeetings/{id}/transcripts`, `…/{tid}/content?$format=text/vtt` | `OnlineMeetingTranscript.Read.All` | **administrateur requis** |

Les permissions sont demandées progressivement : le calendrier à la connexion, les transcripts
uniquement lorsque vous cliquez sur « Vérifier le transcript Teams officiel ».

## Ce que l'application ne fait pas

- Aucune permission « Application » (pas d'accès aux réunions des autres utilisateurs).
- Aucun secret client, aucun mot de passe saisi dans l'application.
- Aucune tentative de contournement : un refus (403) est affiché tel quel et la transcription locale
  reste proposée.

## Limites importantes (documentation Microsoft, vérifiée le 23/10/2026)

1. **Réunions organisées par une autre entreprise** : `GET /me/onlineMeetings` ne retrouve en
   pratique que les réunions de votre tenant. Une réunion d'un tenant externe apparaît comme
   « Réunion non accessible via Graph ». **Teams Premium ne change pas cette limite** ; c'est le cas
   d'usage principal de la transcription locale.
2. L'accès aux transcripts est **régi par les paramètres de l'administrateur** : s'il est désactivé,
   Graph renvoie `403 GraphAccessToTranscriptsDisabled`, sans contournement possible.
3. Le transcript doit avoir été **démarré dans la réunion** (par l'organisateur ou un participant
   autorisé) et la réunion **ne doit pas avoir expiré**.
4. Les réunions créées hors calendrier (API `create onlineMeeting`) ne sont pas prises en charge.
5. La recherche par `joinWebUrl` accepte le jeton de l'organisateur **ou d'un participant invité**,
   mais la lecture des transcripts reste soumise aux règles de votre organisation : à vérifier par test.

Sources : Microsoft Learn — *List transcripts* et *Get onlineMeeting* (Graph v1.0).

## Étapes de configuration (à réaliser par vous ou votre administrateur)

### 1. Enregistrer l'application dans Microsoft Entra ID

1. Portail Entra (https://entra.microsoft.com) > **Applications** > **Inscriptions d'applications** >
   **Nouvelle inscription**.
2. Nom : `TeamsAssistant (usage personnel)`. Types de comptes : **comptes de cet annuaire
   organisationnel uniquement**.
3. URI de redirection : plateforme **Client public / natif (mobile et bureau)**, valeur
   `http://localhost`.
4. Dans **Authentification** : « Autoriser les flux de clients publics » = **Oui**.
5. Notez l'**ID d'application (client)** et l'**ID de l'annuaire (locataire)**.

> Si vous n'avez pas le droit d'inscrire une application, transmettez ces étapes à votre
> service informatique.

### 2. Déclarer les permissions

**API autorisées** > **Ajouter une autorisation** > Microsoft Graph > **Autorisations déléguées** :
`User.Read`, `Calendars.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`.

Demandez ensuite à un administrateur de cliquer **Accorder le consentement administrateur**
(obligatoire pour `OnlineMeetingTranscript.Read.All`).

Texte de demande suggéré :
> « Je souhaite tester un outil personnel de compte rendu de réunions. Il demande en délégué, en lecture
> seule, `Calendars.Read`, `OnlineMeetings.Read` et `OnlineMeetingTranscript.Read.All` afin de récupérer
> les transcripts des réunions Teams auxquelles j'ai accès. Aucune permission application, aucun secret. »

### 3. Configurer TeamsAssistant

Paramètres > Microsoft 365 : saisir l'ID d'application et l'ID d'annuaire (ou `organizations`),
**Enregistrer**, puis **Se connecter** : la page Microsoft s'ouvre dans le navigateur.

Le cache de jetons est stocké dans `%LOCALAPPDATA%\TeamsAssistant\data\msal_token_cache.bin`,
**chiffré par DPAPI** (lisible uniquement par votre session Windows). « Se déconnecter » le vide.

## Dépannage

| Message | Cause probable |
|---|---|
| Consentement requis | Consentement administrateur non accordé |
| Accès refusé (403) | Consentement manquant ou `GraphAccessToTranscriptsDisabled` |
| Réunion non accessible | Réunion d'un autre tenant, ou non liée au calendrier |
| Aucun transcript officiel | La transcription n'a pas été lancée dans Teams, ou réunion expirée |
