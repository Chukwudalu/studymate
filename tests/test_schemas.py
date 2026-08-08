import pytest
from pydantic import ValidationError

from packages.shared_types.schemas import LectureState, LectureSummary, NoteBlock, RawChunk

USER_ID = "11111111-1111-1111-1111-111111111111"


def test_lecture_state_requires_raw_chunks_and_audio_key():
    with pytest.raises(ValidationError):
        LectureState(lecture_id="lec-1", user_id=USER_ID, subject="Biology", status="queued")


def test_lecture_state_requires_user_id():
    with pytest.raises(ValidationError):
        LectureState(
            lecture_id="lec-1",
            subject="Biology",
            status="queued",
            audio_key="lectures/x.mp3",
            raw_chunks=[],
        )


def test_lecture_state_defaults():
    state = LectureState(
        lecture_id="lec-1",
        user_id=USER_ID,
        subject="Biology",
        status="queued",
        audio_key="lectures/x.mp3",
        raw_chunks=[],
    )
    assert state.flashcards_status == "not requested"
    assert state.quiz_status == "not requested"
    assert state.flashcards_count == 10
    assert state.quiz_count == 10
    assert state.segments == []
    assert state.transcription_errors == []
    assert state.flashcards_errors == []
    assert state.quiz_errors == []


def test_lecture_state_rejects_invalid_status():
    with pytest.raises(ValidationError):
        LectureState(
            lecture_id="lec-1",
            user_id=USER_ID,
            subject="Biology",
            status="not-a-real-status",
            audio_key="lectures/x.mp3",
            raw_chunks=[],
        )


def test_raw_chunk_round_trips_in_lecture_state():
    state = LectureState(
        lecture_id="lec-1",
        user_id=USER_ID,
        subject="Biology",
        status="transcribing",
        audio_key="lectures/x.mp3",
        raw_chunks=[{"text": "hello", "start_ms": 0, "end_ms": 1000}],
    )
    assert state.raw_chunks == [RawChunk(text="hello", start_ms=0, end_ms=1000)]


def test_note_block_key_terms_must_be_a_list_not_a_string():
    # Regression guard: key_terms was briefly mistyped as `str` in a past session.
    with pytest.raises(ValidationError):
        NoteBlock(segment_id="seg-1", summary="summary", key_terms="not-a-list")

    note = NoteBlock(segment_id="seg-1", summary="summary", key_terms=["term-a", "term-b"])
    assert note.key_terms == ["term-a", "term-b"]


def test_lecture_summary_coerces_uuid_like_lecture_id_to_str():
    # Regression guard: db.list_lectures once passed a raw UUID object here and pydantic rejected it.
    summary = LectureSummary(
        lecture_id="4b7f7f0e-6e0d-4b0a-9f0a-1f2a3b4c5d6e",
        user_id=USER_ID,
        subject="Biology",
        status="done",
        created_at="2026-08-01T00:00:00Z",
    )
    assert isinstance(summary.lecture_id, str)
