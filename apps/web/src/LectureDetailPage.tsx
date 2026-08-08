import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getLecture, generateFlashcards, generateQuiz, deleteLecture } from "./api";
import type { LectureState } from "./types";
import FlashcardView from "./FlashcardView";
import QuizView from "./QuizView";
import { statusPillClass } from "./utils";

export default function LectureDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [lecture, setLecture] = useState<LectureState | null>(null);
  const [flashcardsCount, setFlashcardsCount] = useState(10);
  const [quizCount, setQuizCount] = useState(10);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (!lecture) return;
    if (!confirm(`Delete this lecture? This can't be undone.`)) return;
    setDeleting(true);
    try {
      await deleteLecture(lecture.lecture_id);
      navigate(`/subject/${encodeURIComponent(lecture.subject)}`);
    } catch {
      setDeleting(false);
    }
  }

  useEffect(() => {
    if (!id) return;

    let cancelled = false;

    async function poll() {
      try {
        const state = await getLecture(id!);
        if (!cancelled) setLecture(state);
      } catch {
        // transient errors are ignored; next poll will retry
      }
    }

    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [id]);

  if (!lecture) {
    return (
      <div className="wrap">
        <p className="lede">Loading…</p>
      </div>
    );
  }

  const notesReady = lecture.status === "done";
  const failed = lecture.status === "failed";

  return (
    <div className="wrap">
      <Link to={`/subject/${encodeURIComponent(lecture.subject)}`} className="breadcrumb-back">
        ← Back to {lecture.subject}
      </Link>

      <section className="card">
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div>
            <h2 className="display">{lecture.subject}</h2>
            <div style={{ fontSize: 13, color: "var(--ink-faint)" }}>Lecture {lecture.lecture_id.slice(0, 8)}</div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className={statusPillClass(lecture.status)}>
              <span className="pill-dot" />
              {lecture.status.replace("_", " ")}
            </span>
            <button className="btn btn-danger" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>

        {failed && lecture.transcription_errors.length > 0 && (
          <div className="error-box">{lecture.transcription_errors[lecture.transcription_errors.length - 1]}</div>
        )}

        {notesReady && (
          <div className="notes">
            <span className="section-label">Notes</span>
            {lecture.notes.map((note) => (
              <div key={note.segment_id} className="note-block">
                <p className="summary">{note.summary}</p>
                <div className="note-terms">
                  {note.key_terms.map((term) => (
                    <span key={term} className="term-chip">{term}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {notesReady && (
          <div className="actions">
            <div className="count-field">
              <input
                type="number"
                min={1}
                max={100}
                value={flashcardsCount}
                onChange={(e) => setFlashcardsCount(Number(e.target.value))}
              />
              <button
                className="btn btn-primary"
                onClick={() => generateFlashcards(lecture.lecture_id, flashcardsCount)}
                disabled={lecture.flashcards_status === "queued" || lecture.flashcards_status === "generating"}
              >
                Generate flashcards
              </button>
            </div>
            <div className="count-field">
              <input
                type="number"
                min={1}
                max={100}
                value={quizCount}
                onChange={(e) => setQuizCount(Number(e.target.value))}
              />
              <button
                className="btn btn-ghost"
                onClick={() => generateQuiz(lecture.lecture_id, quizCount)}
                disabled={lecture.quiz_status === "queued" || lecture.quiz_status === "generating"}
              >
                Generate quiz
              </button>
            </div>
          </div>
        )}

        {lecture.flashcards_status === "failed" && lecture.flashcards_errors.length > 0 && (
          <div className="error-box">{lecture.flashcards_errors[lecture.flashcards_errors.length - 1]}</div>
        )}

        {lecture.quiz_status === "failed" && lecture.quiz_errors.length > 0 && (
          <div className="error-box">{lecture.quiz_errors[lecture.quiz_errors.length - 1]}</div>
        )}
      </section>

      {lecture.flashcards.length > 0 && (
        <section className="card">
          <FlashcardView flashcards={lecture.flashcards} />
        </section>
      )}

      {lecture.quiz.length > 0 && (
        <section className="card">
          <QuizView quiz={lecture.quiz} />
        </section>
      )}
    </div>
  );
}
