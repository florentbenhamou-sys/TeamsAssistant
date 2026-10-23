"""Générateur local, sans IA ni réseau : extraction prudente par règles (français).

Il ne rédige pas : il repère et cite des phrases de la transcription (décisions, actions,
questions, risques) en conservant les références aux segments. Les échéances ne sont
reprises que si elles figurent mot pour mot ; aucun responsable n'est attribué.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from teams_assistant.models import TranscriptSegment
from teams_assistant.summary.schema import (
    EXTRACT,
    FACT,
    INTERPRETATION,
    SummaryContent,
    SummaryInput,
    SummaryItem,
    format_duration,
    participant_entries,
)

NOTICE = ("Compte rendu généré localement par extraction de phrases (sans IA). Le résumé exécutif "
          "et les sujets sont indicatifs : relisez, complétez et validez avant diffusion.")

PATTERNS: dict[str, re.Pattern[str]] = {
    "decisions": re.compile(r"\b(nous validons|on valide|validé|décid|nous retenons|on retient|acté|"
                            r"d'accord pour|nous choisissons|c'est entendu pour)", re.I),
    "commitments": re.compile(r"\b(je vous (envoie|enverrai|transmet|transmettrai)|je vais|je m'engage|"
                              r"nous (allons|préparerons|enverrons|transmettrons|vous transmettrons|"
                              r"vous enverrons|nous engageons)|on va|je m'occupe|nous nous occupons)", re.I),
    "risks": re.compile(r"\b(risque|inquiétude|inquiet|difficulté|problème|bloquant|objection|crainte|"
                        r"frein|contrainte|retard)", re.I),
    "open_questions": re.compile(r"(question ouverte|pas encore tranché|reste à (définir|déterminer|voir)|"
                                 r"à confirmer|à clarifier|on ne sait pas)", re.I),
    "context": re.compile(r"\b(objectif|ordre du jour|le but|l'enjeu|réunion de|afin de)", re.I),
}
MONTHS = r"(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)"
DUE_PATTERN = re.compile(
    r"\b((d'ici|avant|pour|au plus tard) (le |la |la fin de |fin )?"
    rf"((\d{{1,2}}(er)?|[a-z-]+) {MONTHS}|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|"
    r"la semaine prochaine|semaine prochaine|fin du mois|\w+ prochain(e)?)( prochain(e)?)?|"
    r"(lundi|mardi|mercredi|jeudi|vendredi) prochain)", re.I)
STOPWORDS = set("""a à au aux avec ce ces cette d de des du elle en est et être il ils je la le les leur
lui mais me même mes moi mon ne nos notre nous on ou où par pas pour qu que qui sa se ses son sur ta te
tes toi ton tu un une vos votre vous y c ça cela été sont ont avons avez fait faire bien très plus tout
tous toute toutes alors donc aussi comme dans entre sans sous chez si non oui merci bonjour bonne journée
peut pouvez pouvons va vais allons d'accord parfait entendu reste côté""".split())


@dataclass
class Sentence:
    text: str
    refs: list[int] = field(default_factory=list)
    speaker: str = ""


def utterances(segments: list[TranscriptSegment]) -> list[Sentence]:
    """Regroupe les segments consécutifs d'une même source coupés en milieu de phrase."""
    merged: list[Sentence] = []
    for seg in segments:
        previous = merged[-1] if merged else None
        if previous and previous.speaker == (seg.speaker or "") and not re.search(r"[.!?]$", previous.text):
            previous.text = f"{previous.text} {seg.text}".strip()
            previous.refs.append(seg.seq)
        else:
            merged.append(Sentence(seg.text.strip(), [seg.seq], seg.speaker or ""))
    return merged


def sentences(segments: list[TranscriptSegment]) -> list[Sentence]:
    result: list[Sentence] = []
    for utterance in utterances(segments):
        for part in re.split(r"(?<=[.!?])\s+", utterance.text):
            if len(part.split()) >= 3:
                result.append(Sentence(part.strip(), list(utterance.refs), utterance.speaker))
    return result


def _item(sentence: Sentence, kind: str = FACT) -> SummaryItem:
    return SummaryItem(text=sentence.text, kind=kind, refs=sentence.refs, speaker=sentence.speaker)


def _action(sentence: Sentence) -> SummaryItem:
    item = _item(sentence)
    due = DUE_PATTERN.search(sentence.text)
    item.due = due.group(0) if due else ""  # échéance reprise uniquement si citée
    return item


def _topics(all_sentences: list[Sentence], limit: int = 6) -> list[SummaryItem]:
    words = Counter(w for s in all_sentences for w in re.findall(r"[a-zàâçéèêëîïôûùüÿœ'-]{4,}", s.text.lower())
                    if w not in STOPWORDS)
    frequent = [w for w, count in words.most_common(limit) if count >= 2]
    if not frequent:
        return []
    return [SummaryItem(text=f"Termes les plus fréquents : {', '.join(frequent)}", kind=INTERPRETATION)]


def _validation_points(data: SummaryInput) -> list[SummaryItem]:
    points = [SummaryItem(text=f"Passage peu fiable à vérifier : « {s.text} »", kind=FACT, refs=[s.seq],
                          speaker=s.speaker or "") for s in data.segments if s.uncertain]
    points.append(SummaryItem(text="Les responsables des actions ne sont pas attribués automatiquement : "
                                   "à compléter uniquement s'ils ont été explicitement désignés.",
                              kind=INTERPRETATION))
    points.append(SummaryItem(text="Les questions listées ont pu recevoir une réponse pendant la réunion : "
                                   "à vérifier.", kind=INTERPRETATION))
    if any(s.speaker for s in data.segments):
        points.append(SummaryItem(text="Les intervenants sont des sources audio (micro local / son du PC), "
                                       "pas des personnes identifiées.", kind=INTERPRETATION))
    return points


class LocalSummaryGenerator:
    name = "local-regles"

    def generate(self, data: SummaryInput) -> SummaryContent:
        content = SummaryContent(title=data.title, date=data.date, duration=format_duration(data.duration_s),
                                 participants=participant_entries(data), generator_notice=NOTICE)
        all_sentences = sentences(data.segments)
        for sentence in all_sentences:
            self._classify(sentence, content)
        content.sections["next_actions"] = [_action(Sentence(i.text, i.refs, i.speaker))
                                            for i in content.sections["commitments"]]
        content.sections["topics"] = _topics(all_sentences)
        content.sections["executive_summary"] = self._executive(content)
        content.sections["validation_points"] = _validation_points(data)
        return content

    @staticmethod
    def _classify(sentence: Sentence, content: SummaryContent) -> None:
        for key, pattern in PATTERNS.items():
            if pattern.search(sentence.text):
                content.sections[key].append(_item(sentence))
        if sentence.text.endswith("?") and not PATTERNS["open_questions"].search(sentence.text):
            content.sections["open_questions"].append(_item(sentence))

    @staticmethod
    def _executive(content: SummaryContent) -> list[SummaryItem]:
        # Résumé extractif : premières phrases de contexte et de décision, signalées comme extraits
        picks = content.sections["context"][:2] + content.sections["decisions"][:3]
        return [SummaryItem(text=i.text, kind=EXTRACT, refs=i.refs, speaker=i.speaker) for i in picks]
