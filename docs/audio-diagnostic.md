# Guide de diagnostic audio

## Principe de capture

- **Son de la réunion** : WASAPI *loopback* — on enregistre ce que Windows envoie à une sortie
  (casque, haut-parleurs). Cela fonctionne identiquement avec Teams Desktop et Teams dans un
  navigateur, puisque l'on capte la sortie et non l'application.
- **Microphone** (optionnel, désactivé par défaut) : entrée WASAPI partagée, enregistrée dans un
  fichier séparé.
- Aucune interaction avec Teams : pas d'injection, pas de bot, pas de contournement.

## Outil de diagnostic

Depuis le dossier du projet (après `scripts\setup.ps1`) :

```powershell
scripts\diag.ps1 list                         # périphériques, deux backends
scripts\diag.ps1 record --seconds 5 --tone    # capture loopback + bip de test 440 Hz discret
scripts\diag.ps1 record --kind input --seconds 5   # micro : parlez pendant le test
scripts\diag.ps1 probe                        # pendant une réunion : quelle sortie reçoit le son ?
scripts\diag.ps1 check C:\chemin\fichier.wav  # vérifier un fichier
scripts\diag.ps1 --backend wasapi-soundcard record --tone   # backend de repli
```

Codes retour : `0` capture validée (fichier lisible **et** signal détecté) · `2` fichier lisible mais
sans signal · `1` erreur. Les fichiers de test vont dans `%LOCALAPPDATA%\TeamsAssistant\data\recordings\diagnostic`.

Critère « signal détecté » : crête > -50 dBFS et au moins 1 % d'échantillons au-dessus de ~-50 dBFS.

## Résultats mesurés sur le poste (23/10/2026)

| Test | Backend | Résultat |
|---|---|---|
| Loopback casque Jabra + bip 5 s | PyAudioWPatch | ✅ 5,0 s, crête -27 dBFS (bip émis à -26 dBFS), 1,1 s de silence comblé |
| Loopback casque Jabra + bip 4 s | soundcard | ✅ 3,9 s, crête -26,6 dBFS |
| Loopback casque sans aucun son | PyAudioWPatch | ✅ correctement déclaré « NON VALIDÉE » (0 trame livrée, 3 s comblées) |
| Loopback haut-parleurs Realtek + bip | PyAudioWPatch | ✅ crête -18,9 dBFS |
| Micro Jabra, sans voix | PyAudioWPatch | 🟡 flux ouvert, bruit de fond -63 dBFS ; ~1 s de latence à l'ouverture |
| Micro Realtek, sans voix | PyAudioWPatch / soundcard | 🟡 flux régulier 48 000 trames/s, bruit de fond -47 dBFS |
| Session loopback + micro avec pause 1 s | les deux | ✅ durée = temps actif (pause exclue) ; écart micro/système < 0,05 s (PyAudio), ~0,27 s (soundcard) |

**Non testé par moi** (nécessite votre intervention) : voix réelle au micro, réunion Teams réelle
(Desktop et navigateur), débranchement physique d'un casque pendant une capture.

## Limites constatées

1. **Pas de trames pendant le silence** en loopback WASAPI. Le recorder insère du silence d'après
   l'horloge système pour garder des horodatages justes. Effet de bord : le vumètre reste à zéro
   quand personne ne parle — c'est normal.
2. **Le loopback capte tout le son du PC** sur la sortie choisie (notifications, vidéo, musique).
   Coupez les autres sources pendant la réunion, ou dédiez une sortie à Teams.
3. **Teams peut utiliser une sortie différente** de la sortie par défaut de Windows. Choisissez la
   sortie indiquée dans Teams > Paramètres > Périphériques, ou utilisez `probe`.
4. **Casque sans fil** : il peut disparaître de la liste (constaté pendant les tests) ; les index
   changent. L'application résout les périphériques par nom et signale l'interruption ; l'audio
   enregistré jusqu'à la coupure est conservé.
5. **Micro Bluetooth/DECT** : ~1 s de latence à l'ouverture (bascule mains-libres), comblée par du
   silence en début de fichier.
6. **Mode exclusif** : si une application a pris le contrôle exclusif du périphérique, l'ouverture
   échoue avec un message explicite.
7. Le backend soundcard émet des avertissements « data discontinuity » lors des silences : sans
   conséquence sur le fichier, mais l'alignement est moins précis (~0,3 s).

## Dépannage

| Symptôme | Action |
|---|---|
| « AUCUN SIGNAL » en loopback | Vérifier que du son est joué ; vérifier la sortie Teams ; `probe` |
| « AUCUN SIGNAL » au micro | Confidentialité Windows > Microphone > applications de bureau ; bouton mute du casque |
| « Périphérique introuvable » | Rebrancher / rallumer le casque, actualiser la liste |
| « Impossible d'ouvrir » | Désactiver le mode exclusif (Panneau Son > Propriétés > Avancé) ; fermer l'appli qui l'utilise |
| Rien ne marche avec un backend | `--backend wasapi-soundcard` (ou inversement) |
| Service audio | `Get-Service audiosrv` doit être « Running » |
