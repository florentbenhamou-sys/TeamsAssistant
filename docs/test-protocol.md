# Protocole de test manuel

À réaliser **uniquement dans un contexte autorisé** : réunion de test avec des collègues prévenus,
ou réunion réelle dont les participants ont été informés. Notez pour chaque test : date, résultat
(OK / KO), remarques. Les tests marqués ✅ ont déjà été exécutés par l'assistant de développement ;
tous les autres restent à faire par vous.

## 0. Pré-requis

1. `TeamsAssistant.bat` (premier lancement : préparation de l'environnement, quelques minutes).
2. `scripts\diag.ps1 record --seconds 5 --tone` → « capture VALIDÉE » (✅ fait le 23/10/2026 sur le
   casque Jabra et les haut-parleurs Realtek).

## 1. Teams Desktop

1. Créez une réunion de test Teams avec un collègue (ou rejoignez une réunion autorisée).
2. Dans Teams : Paramètres > Périphériques, notez le **haut-parleur** utilisé.
3. TeamsAssistant > Nouvelle session : titre, sortie = celle notée, micro **non coché**.
4. Cochez la confirmation des autorisations, **Démarrer la capture**.
5. Vérifiez : bandeau rouge « ENREGISTREMENT EN COURS » visible sur tous les écrans, durée qui
   avance, vumètre « Son du PC » qui bouge quand le collègue parle.
6. **Suspendre** 10 s (bandeau orange), **Reprendre**, puis **Arrêter** après ~2 min.
7. Attendu : « Audio exploitable enregistré », durée ≈ durée réelle moins la pause.
8. Transcription > Transcrire : texte français cohérent, horodatages plausibles.

## 2. Teams dans un navigateur (Edge / Chrome)

Mêmes étapes que 1, la réunion étant ouverte dans le navigateur. Vérifiez au préalable la sortie
audio du navigateur (Paramètres Windows > Son > Mélangeur de volume). Attendu identique.

## 3. Casque avec microphone

1. Nouvelle session avec la sortie **casque** et **micro coché** (micro du casque).
2. Parlez à tour de rôle avec le collègue.
3. Attendu : deux fichiers (system.wav, microphone.wav) ; transcription avec « Micro local » pour vos
   phrases et « Participants distants » pour celles du collègue ; pas de doublons.
4. Test de robustesse : éteignez/débranchez le casque pendant la capture → une alerte « flux
   interrompu » ou « le microphone ne transmet plus de données » doit apparaître ; à l'arrêt,
   l'audio enregistré avant la coupure est conservé. (Non testé physiquement à ce jour.)

## 4. Haut-parleurs du PC

1. Sortie = haut-parleurs, micro coché (micro intégré).
2. Attendu : la voix du collègue est captée deux fois (loopback + micro) ; la transcription doit
   **retirer l'écho** (« N segment(s) du micro ignoré(s) : écho »). Notez les doublons restants.
3. Variante recommandée si l'écho persiste : Paramètres > décocher « Transcrire séparément ».

## 5. Réunion dont le transcript officiel est accessible (M365)

Pré-requis : [`microsoft-graph.md`](microsoft-graph.md) étapes 1–3, consentement administrateur.
1. Réunion de **votre** organisation, transcription Teams démarrée pendant la réunion.
2. Après la réunion : Nouvelle session en sélectionnant la réunion Outlook, puis Transcription >
   « Vérifier le transcript Teams officiel ».
3. Attendu : « Transcript officiel accessible » → « Importer » → segments avec les noms Teams.

## 6. Réunion dont le transcript officiel n'est pas accessible

1. Réunion organisée par une **autre entreprise** (ou sans transcription Teams).
2. « Vérifier le transcript Teams officiel ».
3. Attendu : « Réunion non accessible via Graph » ou « Aucun transcript officiel », **sans erreur
   bloquante** ; la transcription locale reste disponible.

## 7. Transcription locale sans service externe

1. Coupez le réseau (mode avion) **après** le premier téléchargement du modèle.
2. Paramètres : IA cloud désactivée.
3. Transcrivez une session puis générez le compte rendu (générateur local).
4. Attendu : tout fonctionne hors connexion. (✅ vérifié sur l'échantillon synthétique avec le
   modèle déjà téléchargé ; non vérifié en mode avion.)

## 8. Historique, exports, suppression

1. Historique : recherche d'un mot présent dans une transcription → la session apparaît.
2. Renommer, Exporter (dossier) : fichiers .md / .json créés.
3. Compte rendu : modifier un élément, Valider, Exporter DOCX et l'ouvrir dans Word.
4. Supprimer la session → elle disparaît, son dossier `recordings\<id>` aussi ; un fichier que vous
   aviez importé reste intact.
