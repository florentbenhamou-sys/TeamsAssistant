"""Séparation des voix (diarisation) locale.

Méthode (choisie après mesures, voir docs/separation-des-voix.md) :
1. la transcription est découpée en prises de parole courtes (pauses, fins de phrase) ;
2. une caractéristique vocale est calculée pour chaque prise de parole (modèle TitaNet, sherpa-onnx) ;
3. les prises de parole sont regroupées par ressemblance (regroupement hiérarchique, cosinus) ;
4. les groupes sont numérotés dans leur ordre d'apparition : « Intervenant 1 », « 2 »…

Confidentialité (choix délibéré, RGPD) : les caractéristiques vocales n'existent qu'en mémoire,
le temps de traiter UNE piste, puis sont détruites. Aucune empreinte vocale n'est enregistrée,
comparée entre réunions ni associée à une identité ; le nommage est fait par l'utilisateur.
"""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

from teams_assistant.logging_setup import get_logger
from teams_assistant.transcription.types import SAMPLE_RATE, Samples, SourceKind, TranscriptionError

log = get_logger("transcription.diarization")
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# TitaNet small : meilleur résultat mesuré (4/4 enregistrements réels au bon nombre de voix,
# séparation nette sur l'échantillon français : similarité 0,83+ même voix, 0,54- voix différentes)
EMBEDDING_FILE = "nemo_en_titanet_small.onnx"
EMBEDDING_URL = f"{RELEASES}/speaker-recongition-models/{EMBEDDING_FILE}"
# Similarité moyenne minimale pour fusionner deux groupes en mode automatique. Mesuré sur 5 fichiers
# (4 réels, 1 synthétique) : 0,45 -> nombre exact 4 fois sur 5, une voix de trop sinon ; 0,40 fusionne
# deux voix différentes (erreur irréparable par renommage) ; 0,60 compte 5 voix au lieu de 2.
AUTO_THRESHOLD = 0.45
MIN_EMBED_S = 1.0  # en dessous, la caractéristique vocale est peu fiable : rattachement a posteriori
MIN_ATTACH_S = 0.3  # en dessous, on reprend la voix de la prise de parole voisine
NUM_THREADS = max(1, (os.cpu_count() or 2) // 2)

# Préfixe des libellés selon la piste : distingue les voix de la salle de celles à distance
LABEL_PREFIX: dict[SourceKind, str] = {
    SourceKind.SYSTEM: "Distant",
    SourceKind.MICROPHONE: "Salle",
    SourceKind.IMPORTED: "Intervenant",
    SourceKind.MIXED: "Intervenant",
    SourceKind.TEAMS: "Intervenant",
}

Span = tuple[float, float]  # début, fin en secondes
Matrix = npt.NDArray[np.float64]


class Diarizer(Protocol):
    def assign(self, samples: Samples, spans: Sequence[Span], num_speakers: int = 0,
               progress: Callable[[float], None] | None = None) -> list[int]:
        """Numéro de voix (1, 2…) pour chaque intervalle, dans l'ordre fourni."""
        ...


def model_path(models_dir: Path) -> Path:
    return models_dir / "diarization" / EMBEDDING_FILE


def ensure_model(models_dir: Path) -> Path:
    """Télécharge une fois le modèle (~38 Mo, GitHub sherpa-onnx) dans le dossier des modèles."""
    target = model_path(models_dir)
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    log.info("Téléchargement du modèle %s", target.name)
    try:
        with urllib.request.urlopen(EMBEDDING_URL, timeout=60) as response, partial.open("wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
    except OSError as exc:
        raise TranscriptionError(f"Téléchargement du modèle de séparation des voix impossible : {exc}. "
                                 "Une connexion Internet est nécessaire au premier usage.") from exc
    partial.replace(target)
    return target


# --- regroupement ---------------------------------------------------------------------------
def cluster(vectors: Matrix, num_speakers: int = 0, threshold: float = AUTO_THRESHOLD) -> list[int]:
    """Regroupement hiérarchique à lien moyen (cosinus) : nombre imposé, ou seuil si 0."""
    count = len(vectors)
    if count == 0:
        return []
    unit = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
    sim = unit @ unit.T
    np.fill_diagonal(sim, -np.inf)
    sizes, groups = np.ones(count), {i: [i] for i in range(count)}
    while len(groups) > max(num_speakers, 1):
        i, j = np.unravel_index(int(np.argmax(sim)), sim.shape)
        if num_speakers <= 0 and sim[i, j] < threshold:
            break
        _merge(sim, sizes, groups, int(min(i, j)), int(max(i, j)))
    labels = [0] * count
    for number, members in enumerate(groups.values(), start=1):
        for member in members:
            labels[member] = number
    return labels


def _merge(sim: Matrix, sizes: npt.NDArray[np.float64], groups: dict[int, list[int]], i: int, j: int) -> None:
    # Mise à jour de Lance-Williams pour le lien moyen
    merged = (sizes[i] * sim[i] + sizes[j] * sim[j]) / (sizes[i] + sizes[j])
    sim[i], sim[:, i] = merged, merged
    sim[i, i] = -np.inf
    sim[j], sim[:, j] = -np.inf, -np.inf
    sizes[i] += sizes[j]
    groups[i].extend(groups.pop(j))


def renumber(labels: Sequence[int], spans: Sequence[Span]) -> list[int]:
    """Numérote les voix 1, 2, 3… dans leur ordre de première apparition (résultat stable)."""
    order: dict[int, int] = {}
    for index in sorted(range(len(spans)), key=lambda k: spans[k][0]):
        order.setdefault(labels[index], len(order) + 1)
    return [order[label] for label in labels]


def attach_short(labels: list[int | None], vectors: dict[int, npt.NDArray[np.float64]],
                 spans: Sequence[Span]) -> list[int]:
    """Rattache les prises de parole trop courtes : au groupe le plus ressemblant, sinon au voisin."""
    centroids = _centroids(labels, vectors)
    resolved: list[int | None] = list(labels)
    for index, label in enumerate(labels):
        if label is None and index in vectors and centroids:
            resolved[index] = max(centroids, key=lambda k: float(centroids[k] @ vectors[index]))
    return [value if value is not None else _neighbour(resolved, spans, i) for i, value in enumerate(resolved)]


def _centroids(labels: list[int | None], vectors: dict[int, npt.NDArray[np.float64]]) -> dict[int, Any]:
    sums: dict[int, Any] = {}
    for index, label in enumerate(labels):
        if label is not None and index in vectors:
            sums[label] = sums.get(label, 0) + vectors[index]
    return {k: v / max(float(np.linalg.norm(v)), 1e-9) for k, v in sums.items()}


def _neighbour(labels: list[int | None], spans: Sequence[Span], index: int) -> int:
    known = [(abs(spans[k][0] - spans[index][0]), labels[k]) for k in range(len(labels)) if labels[k] is not None]
    return min(known, key=lambda item: item[0])[1] or 1 if known else 1


# --- extraction des caractéristiques vocales ----------------------------------------------------
class EmbeddingDiarizer:
    def __init__(self, model: Path, threshold: float = AUTO_THRESHOLD) -> None:
        self.model = model
        self.threshold = threshold

    def _extractor(self) -> Any:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise TranscriptionError("sherpa-onnx n'est pas installé (scripts\\setup.ps1).") from exc
        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.model), num_threads=NUM_THREADS)
        return sherpa_onnx.SpeakerEmbeddingExtractor(config)

    def assign(self, samples: Samples, spans: Sequence[Span], num_speakers: int = 0,
               progress: Callable[[float], None] | None = None) -> list[int]:
        if not spans:
            return []
        vectors = self._embed_all(samples, spans, progress)
        long_ids = [i for i, (s, e) in enumerate(spans) if e - s >= MIN_EMBED_S and i in vectors]
        if not long_ids:
            return [1] * len(spans)  # trop peu de parole exploitable : une seule voix supposée
        grouped = cluster(np.stack([vectors[i] for i in long_ids]), num_speakers, self.threshold)
        labels: list[int | None] = [None] * len(spans)
        for index, label in zip(long_ids, grouped):
            labels[index] = label
        return renumber(attach_short(labels, vectors, spans), spans)

    def _embed_all(self, samples: Samples, spans: Sequence[Span],
                   progress: Callable[[float], None] | None) -> dict[int, npt.NDArray[np.float64]]:
        extractor, vectors = self._extractor(), {}
        for index, (start, end) in enumerate(spans):
            if end - start >= MIN_ATTACH_S:
                piece = samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
                stream = extractor.create_stream()
                stream.accept_waveform(SAMPLE_RATE, piece)
                stream.input_finished()
                vector = np.asarray(extractor.compute(stream), dtype=np.float64)
                vectors[index] = vector / max(float(np.linalg.norm(vector)), 1e-9)
            if progress:
                progress((index + 1) / len(spans))
        return vectors
