# Séparation des voix (diarisation)

## Ce que fait l'application

Lorsqu'une piste contient plusieurs personnes (plusieurs participants distants sur le son du PC,
ou plusieurs personnes dans la salle autour du même micro), la transcription peut distinguer les
voix : « Distant 1 », « Distant 2 »… pour le son du PC, « Salle 1 », « Salle 2 »… pour le micro,
« Intervenant 1 »… pour un fichier importé.

Ces libellés sont **techniques** : l'application ne sait pas qui parle. Dans l'écran Transcription,
choisissez un intervenant dans la liste (tous ses passages sont surlignés), relisez-les, puis
**Renommer…**. Donner le même nom à deux libellés les **fusionne** (utile quand l'outil a coupé une
même personne en deux).

## Réglages

| Réglage | Effet |
|---|---|
| Distinguer les voix | Active la séparation (Paramètres pour la valeur par défaut, écran Transcription pour la session) |
| Voix sur le son du PC / fichier | Nombre de personnes attendu ; « auto » = estimation |
| Voix au micro | 1 (défaut) = vous seul au casque : pas de séparation ; sinon nombre de personnes dans la salle |

**Indiquez le nombre de personnes dès que vous le connaissez** : c'est le facteur qui améliore le plus
le résultat.

## Confidentialité — aucune empreinte vocale

- Les caractéristiques vocales sont calculées **en mémoire**, uniquement pendant le traitement d'une
  piste, puis détruites.
- Rien n'est enregistré (vérifié par un test automatisé qui contrôle qu'aucun fichier n'est créé),
  rien n'est comparé d'une réunion à l'autre, aucune voix n'est associée à une identité.
- Conséquence : « Intervenant 1 » n'est pas forcément la même personne d'une réunion à l'autre.
- Traitement 100 % local (aucun envoi).

## Méthode

1. Pendant la transcription, chaque segment Whisper est découpé en prises de parole courtes, aux
   pauses (≥ 0,4 s) et aux fins de phrase, grâce aux horodatages par mot.
2. Pour chaque prise de parole d'au moins 1 s, une caractéristique vocale est calculée avec le modèle
   **NeMo TitaNet small** (sherpa-onnx, ~38 Mo, téléchargé une fois depuis GitHub).
3. Regroupement hiérarchique (lien moyen, similarité cosinus) : jusqu'au nombre indiqué, ou jusqu'au
   seuil 0,45 en mode automatique.
4. Les prises de parole plus courtes sont rattachées au groupe le plus ressemblant ou à leur voisine.
5. Numérotation dans l'ordre d'apparition.

Le regroupement se fait sur la piste entière, en fin de transcription : la numérotation reste
cohérente même après une reprise.

## Mesures réalisées (23/10/2026)

| Jeu de test | Nombre indiqué | Mode automatique |
|---|---|---|
| 4 enregistrements de vraies voix (sherpa-onnx : 1 × 4 voix en chinois, 3 × 2 voix en anglais) | nombre exact 4/4 | 3/4 exact, 1 avec une voix de trop |
| Échantillon synthétique français, 2 voix sur le même micro (`samples/two_voices`) | 7/7 répliques transcrites correctement attribuées | idem |

Seules les **quantités** de voix ont été vérifiées sur les vraies voix (pas de vérité terrain sur les
tours de parole) ; l'attribution réplique par réplique n'a été vérifiée que sur l'échantillon
synthétique.

Approche écartée après mesure : le pipeline de diarisation intégré de sherpa-onnx (segmentation
pyannote) attribuait mal 3 répliques sur 8 de l'échantillon, alors que les caractéristiques vocales
distinguaient parfaitement les deux voix.

## Limites

- **Paroles simultanées** : attribuées à une seule voix.
- **Interventions très courtes** (« oui », « d'accord ») : rattachées par voisinage, souvent à tort.
- **Changement de voix sans pause** : la prise de parole n'est pas coupée, elle reçoit une seule voix.
- **Voix proches** (même genre, même âge, même accent) : risque de fusion ; indiquez le nombre.
- **Mode automatique** : tend à compter une voix de trop (corrigez en fusionnant par renommage).
- **Son Teams compressé** et prise de son de salle éloignée : qualité non mesurée à ce jour.
- **Durée** : environ 0,1 × la durée audio en plus (≈ 5 min par heure sur ce PC), à mesurer en réel.
- Non testé sur une vraie réunion à plusieurs voix françaises : à faire avec l'accord des participants
  (voir `test-protocol.md`, § 9).
