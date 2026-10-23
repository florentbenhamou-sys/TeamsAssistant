"""Sessions, persistance SQLite, import, transcription, reprise, exports, suppression."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from fakes import FakeBackend, FakeClock, FakeSpeechEngine, default_devices, sine_block, tone, write_wav
from teams_assistant import exports
from teams_assistant.app_context import AppContext, build_context
from teams_assistant.audio.capture_session import CaptureSession
from teams_assistant.audio.types import DeviceKind
from teams_assistant.config import AppPaths
from teams_assistant.models import AudioFile, SessionStatus, TranscriptStatus
from teams_assistant.services.session_service import SessionError
from teams_assistant.summary.local_generator import LocalSummaryGenerator
from teams_assistant.transcription.types import TranscriptionCancelled, TranscriptionError, TranscriptionOptions


@pytest.fixture()
def ctx(app_paths: AppPaths) -> Iterator[AppContext]:
    context = build_context(app_paths, engine=FakeSpeechEngine())
    yield context
    context.close()


def _imported_session(ctx: AppContext, tmp_path: Path, seconds: float = 3) -> str:
    session = ctx.sessions.create("Réunion test")
    audio = tmp_path / "import.wav"
    write_wav(audio, tone(seconds))
    ctx.sessions.import_audio(session.id, audio)
    return session.id


def test_session_is_persisted_across_connections(app_paths: AppPaths) -> None:
    first = build_context(app_paths, engine=FakeSpeechEngine())
    session_id = first.sessions.create("  Point hebdo  ").id
    first.close()
    second = build_context(app_paths, engine=FakeSpeechEngine())
    loaded = second.sessions.get(session_id)
    assert loaded.title == "Point hebdo" and loaded.status is SessionStatus.DRAFT
    second.close()


def test_empty_title_gets_default_and_unique_ids(ctx: AppContext) -> None:
    a, b = ctx.sessions.create(""), ctx.sessions.create("")
    assert a.id != b.id and a.title.startswith("Réunion du")


def test_import_rejects_missing_and_unsupported_files(ctx: AppContext, tmp_path: Path) -> None:
    session = ctx.sessions.create("x")
    with pytest.raises(SessionError):
        ctx.sessions.import_audio(session.id, tmp_path / "absent.wav")
    bad = tmp_path / "notes.txt"
    bad.write_text("x")
    with pytest.raises(SessionError, match="Format"):
        ctx.sessions.import_audio(session.id, bad)


def test_capture_requires_consent_confirmation(ctx: AppContext) -> None:
    session = ctx.sessions.create("x")
    with pytest.raises(SessionError, match="autorisations"):
        ctx.sessions.mark_capture_started(session.id)
    ctx.sessions.confirm_consent(session.id)
    ctx.sessions.mark_capture_started(session.id)
    assert ctx.sessions.get(session.id).started_at


def test_capture_result_registers_owned_files(ctx: AppContext) -> None:
    session = ctx.sessions.create("capture")
    clock, backend = FakeClock(), FakeBackend()
    capture = CaptureSession(backend, ctx.sessions.recording_dir(session.id), clock)
    capture.start(default_devices()[0])
    clock.advance(1.0)
    backend.streams[DeviceKind.LOOPBACK].emit(sine_block(1.0))
    files = ctx.sessions.attach_capture(session.id, capture.stop())
    assert [f.kind for f in files] == ["system"] and files[0].owned and files[0].has_signal
    assert ctx.sessions.get(session.id).status is SessionStatus.RECORDED


def test_transcription_is_stored_and_searchable(ctx: AppContext, tmp_path: Path) -> None:
    session_id = _imported_session(ctx, tmp_path)
    transcript = ctx.transcription.transcribe(session_id, TranscriptionOptions())
    segments = ctx.transcription.segments(transcript.id)
    assert transcript.status is TranscriptStatus.COMPLETED and [s.seq for s in segments] == [1, 2, 3]
    assert ctx.sessions.get(session_id).status is SessionStatus.TRANSCRIBED
    assert len(ctx.transcription.search(transcript.id, "bonjour 1")) == 1
    assert ctx.sessions.search("bonjour 2")[0].id == session_id  # recherche plein texte de l'historique


def test_correction_keeps_original_text(ctx: AppContext, tmp_path: Path) -> None:
    transcript = ctx.transcription.transcribe(_imported_session(ctx, tmp_path), TranscriptionOptions())
    first = ctx.transcription.segments(transcript.id)[0]
    ctx.transcription.correct_text(first.id, "Bonjour corrigé")
    ctx.transcription.correct_text(first.id, "Bonjour corrigé deux fois")
    updated = ctx.transcription.segments(transcript.id)[0]
    assert updated.text == "Bonjour corrigé deux fois" and updated.original_text == "bonjour 0"
    assert updated.edited
    assert ctx.transcription.rename_speaker(transcript.id, "Fichier importé", "Client A") == 3


def test_interrupted_transcription_resumes(app_paths: AppPaths, tmp_path: Path) -> None:
    failing = build_context(app_paths, engine=FakeSpeechEngine(fail_after=1))
    failing.transcription.pipeline.chunk_target_s = 4
    session_id = _imported_session(failing, tmp_path, seconds=12)
    with pytest.raises(TranscriptionCancelled):
        failing.transcription.transcribe(session_id, TranscriptionOptions())
    interrupted = failing.transcription.latest(session_id)
    assert interrupted is not None and interrupted.status is TranscriptStatus.INTERRUPTED
    assert failing.transcription.can_resume(session_id, TranscriptionOptions())
    failing.close()
    engine = FakeSpeechEngine()
    resumed = build_context(app_paths, engine=engine)
    resumed.transcription.pipeline.chunk_target_s = 4
    transcript = resumed.transcription.transcribe(session_id, TranscriptionOptions())
    assert transcript.id == interrupted.id and transcript.status is TranscriptStatus.COMPLETED
    assert engine.calls >= 2  # le premier tronçon n'est pas retraité
    resumed.close()


def test_transcription_without_audio_fails_clearly(ctx: AppContext) -> None:
    session = ctx.sessions.create("vide")
    with pytest.raises(TranscriptionError, match="Aucun fichier audio"):
        ctx.transcription.transcribe(session.id, TranscriptionOptions())


def test_exports_txt_md_json_docx(ctx: AppContext, tmp_path: Path) -> None:
    session_id = _imported_session(ctx, tmp_path)
    transcript = ctx.transcription.transcribe(session_id, TranscriptionOptions())
    session, segments = ctx.sessions.get(session_id), ctx.transcription.segments(transcript.id)
    txt = exports.transcript_txt(session, segments)
    assert "[00:00:00] Fichier importé : bonjour 0" in txt
    assert "#2" in exports.transcript_md(session, transcript, segments)
    data = json.loads(exports.transcript_json(session, transcript, segments))
    assert len(data["segments"]) == 3 and data["transcript"]["origin"] == "local"
    summary = ctx.summaries.generate(session_id, LocalSummaryGenerator())
    content = ctx.summaries.content(summary)
    assert "BROUILLON" in exports.summary_md(content, summary.validated)
    docx_path = exports.summary_docx(content, False, tmp_path / "cr.docx")
    assert docx_path.stat().st_size > 1000


def test_delete_session_removes_files_and_rows(ctx: AppContext, tmp_path: Path) -> None:
    session = ctx.sessions.create("à supprimer")
    folder = ctx.sessions.recording_dir(session.id)
    folder.mkdir(parents=True)
    owned = folder / "system.wav"
    write_wav(owned, tone(2))
    ctx.sessions.repo.add_audio(AudioFile(session_id=session.id, kind="system", path=str(owned),
                                          owned=True, has_signal=True))
    imported = tmp_path / "mon_fichier.wav"
    write_wav(imported, tone(2))
    ctx.sessions.import_audio(session.id, imported)
    ctx.transcription.transcribe(session.id, TranscriptionOptions())
    ctx.sessions.delete_session(session.id)
    assert not owned.exists() and not folder.exists()
    assert imported.exists()  # le fichier de l'utilisateur n'est jamais supprimé
    for table in ["meeting_session", "audio_file", "transcript", "transcript_segment", "meeting_summary"]:
        assert ctx.db.query(f"SELECT COUNT(*) FROM {table}")[0][0] == 0, table


def test_retention_purges_only_owned_audio(ctx: AppContext, tmp_path: Path) -> None:
    session = ctx.sessions.create("conservation")
    owned = tmp_path / "temp.wav"
    write_wav(owned, tone(1))
    audio = AudioFile(session_id=session.id, kind="system", path=str(owned), owned=True,
                      created_at="2020-01-01T00:00:00+00:00")
    ctx.sessions.repo.add_audio(audio)
    assert ctx.sessions.purge_expired_audio(retention_days=7) == 1
    assert not owned.exists() and ctx.sessions.repo.audio_files(session.id) == []


def test_audio_deleted_after_transcription_when_requested(ctx: AppContext) -> None:
    session = ctx.sessions.create("auto-suppression")
    folder = ctx.sessions.recording_dir(session.id)
    folder.mkdir(parents=True)
    owned = folder / "system.wav"
    write_wav(owned, np.concatenate([tone(2)]))
    ctx.sessions.repo.add_audio(AudioFile(session_id=session.id, kind="system", path=str(owned),
                                          owned=True, has_signal=True))
    ctx.transcription.transcribe(session.id, TranscriptionOptions(), delete_audio_after=True)
    assert not owned.exists()


def test_settings_roundtrip_and_unknown_key(ctx: AppContext) -> None:
    settings = ctx.settings.load()
    assert settings.record_microphone is False and settings.cloud_ai_enabled is False
    ctx.settings.update(transcription_profile="precis", audio_retention_days=3)
    assert ctx.settings.load().transcription_profile == "precis"
    with pytest.raises(KeyError):
        ctx.settings.update(inconnu=1)
