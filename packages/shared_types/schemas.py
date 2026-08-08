from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class RawChunk(BaseModel):
    text: str
    start_ms: int
    end_ms: int

class Segment(BaseModel):
    id:str
    start_ms: int
    end_ms: int
    text: str
    topic_label: str | None = None


class NoteBlock(BaseModel):
    segment_id: str
    summary: str
    key_terms: list[str]
    rolling_context_used: str | None = None


class Flashcard(BaseModel):
    id: str
    front: str
    back: str
    source_segment_id: str
    difficulty: Literal["easy", "medium", "hard"] | None = None


class QuizQuestion(BaseModel):
    id:str
    question: str
    choices: list[str]
    correct_option: str
    explanation: str
    source_segment_id: str


class LectureSummary(BaseModel):
    lecture_id: str
    user_id: str
    subject: str
    status: str
    created_at: datetime


class LectureState(BaseModel):
    lecture_id: str
    user_id: str
    subject: str
    status: Literal["queued", "transcribing", "segmenting", "generating_notes", "done", "failed"]
    flashcards_status: Literal["not requested", "queued", "generating", "done", "failed"] = "not requested"
    quiz_status: Literal["not requested", "queued", "generating", "done", "failed"] = "not requested"
    raw_transcript: str | None = None
    raw_chunks:list[RawChunk]
    audio_key: str
    flashcards_count: int = 10
    quiz_count: int = 10
    segments: list[Segment] = []
    notes: list[NoteBlock] = []
    flashcards: list[Flashcard] = []
    quiz: list[QuizQuestion] = []
    transcription_errors: list[str] = []
    flashcards_errors: list[str] = []
    quiz_errors: list[str] = []


