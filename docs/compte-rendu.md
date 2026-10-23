# Comptes rendus : modèle, générateurs, coûts

## Modèle de compte rendu

```markdown
# <Titre de la réunion>

**Date** : <date ou « inconnue »> · **Durée** : <durée ou « inconnue »>
**Statut** : BROUILLON — non validé | validé par l'utilisateur
> <avertissement du générateur>

## Participants
- <Nom> — identité confirmée (outlook (invité))
- Micro local — identité incertaine (source audio (séparation technique))

## Contexte et objectif
## Résumé exécutif
## Principaux sujets abordés
## Décisions prises
## Questions ouvertes
## Difficultés, objections et risques
## Engagements pris
## Prochaines actions
## Points nécessitant une validation humaine
```

Chaque élément est suivi de sa nature et de ses références, par exemple :
`- Je vous envoie la proposition commerciale d'ici vendredi prochain. (échéance : d'ici vendredi prochain · source : Micro local · segments #12)`

- *(sans mention)* = **fait** énoncé dans la transcription ;
- *interprétation* = déduction, à vérifier ;
- *extrait* = phrase citée automatiquement (résumé local).

Exemple complet généré à partir de l'échantillon synthétique : [`samples/meeting_demo/compte-rendu-exemple.md`](../samples/meeting_demo/compte-rendu-exemple.md).

## Règles appliquées par tous les générateurs

- Aucune décision, aucun participant, aucun engagement inventé.
- Responsable et échéance **uniquement** s'ils figurent explicitement dans la transcription
  (le générateur local n'attribue **jamais** de responsable).
- Les intervenants « Micro local » / « Participants distants » sont des **sources audio**, pas des personnes.
- Les passages à faible confiance sont listés dans « Points nécessitant une validation humaine ».
- Chaque élément renvoie aux segments (bouton « Voir le passage » dans l'écran E).
- Générateur cloud : toute référence à un segment inexistant est retirée ; un élément sans source
  est rétrogradé en « interprétation ».

## Générateur local (par défaut)

Extraction par règles, en français, sans IA ni réseau. Fiable pour repérer les phrases de décision,
d'engagement, de question et de risque ; **ne rédige pas** de synthèse : le résumé exécutif est un
ensemble d'extraits à reformuler. Limites : formulations inhabituelles non détectées, faux positifs
possibles (ex. « problème » dans une phrase anodine).

## Générateur cloud Claude (optionnel, désactivé par défaut)

Activation : Paramètres > « Autoriser l'IA cloud », clé API Anthropic enregistrée (stockée dans le
Gestionnaire d'identification Windows), puis **confirmation à chaque génération**.
Seul le **texte** de la transcription est envoyé (jamais l'audio). Modèle par défaut :
`claude-opus-5-5`, sortie JSON structurée, repli serveur automatique en cas de refus.

**Coût (payant à l'usage)** — tarif public `claude-opus-5-5` : 4 $ / million de jetons en entrée,
20 $ / million en sortie. Ordre de grandeur pour une réunion d'1 h (~10 000 mots ≈ 15–20 k jetons
d'entrée, ~3 k jetons de sortie) : **environ 0,10 à 0,15 $ par compte rendu**. Estimation, non
mesurée sur une vraie réunion.

> Vérifiez que l'envoi de transcriptions de réunions à un service tiers est compatible avec la
> politique de votre entreprise et les engagements pris envers les participants.

**Statut** : code écrit, appel construit selon la documentation du SDK, logique de filtrage testée ;
**aucun appel réel n'a été effectué** (pas de clé API dans cet environnement).
