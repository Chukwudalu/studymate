from apps.api.db import get_lecture, update_lecture_fields
from services.pipeline.transcription_graph import transcription_graph
from services.pipeline.flashcards_graph import flashcards_graph
from services.pipeline.quiz_graph import quiz_graph
from packages.shared_types.schemas import LectureState


def run_transcription_job(lecture_id: str) -> None:
    state = get_lecture(lecture_id)
    try:
        result = transcription_graph.invoke(state)
        updated_state = LectureState.model_validate(result)
    except Exception as e:
        update_lecture_fields(lecture_id, status="failed", transcription_errors=[str(e)])
        raise

    update_lecture_fields(
        lecture_id,
        status=updated_state.status,
        raw_transcript=updated_state.raw_transcript,
        raw_chunks=[c.model_dump() for c in updated_state.raw_chunks],
        segments=[s.model_dump() for s in updated_state.segments],
        notes=[n.model_dump() for n in updated_state.notes],
        transcription_errors=[],
    )


def run_flashcards_job(lecture_id: str) -> None:
    state = get_lecture(lecture_id)
    try:
        result = flashcards_graph.invoke(state)
        updated_state = LectureState.model_validate(result)
    except Exception as e:
        update_lecture_fields(lecture_id, flashcards_status="failed", flashcards_errors=[str(e)])
        raise

    update_lecture_fields(
        lecture_id,
        flashcards=[f.model_dump() for f in updated_state.flashcards],
        flashcards_status="done",
        flashcards_errors=[],
    )


def run_quiz_job(lecture_id: str) -> None:
    state = get_lecture(lecture_id)
    try:
        result = quiz_graph.invoke(state)
        updated_state = LectureState.model_validate(result)
    except Exception as e:
        update_lecture_fields(lecture_id, quiz_status="failed", quiz_errors=[str(e)])
        raise

    update_lecture_fields(
        lecture_id,
        quiz=[q.model_dump() for q in updated_state.quiz],
        quiz_status="done",
        quiz_errors=[],
    )
