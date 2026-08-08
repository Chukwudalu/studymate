import os
import json
import psycopg
from packages.shared_types.schemas import LectureState, LectureSummary

DATABASE_URL = os.environ["DATABASE_URL"]

def get_connection():
    return psycopg.connect(DATABASE_URL)


def create_lecture(state: LectureState) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO lectures (id, state) VALUES (%s, %s)",
            (state.lecture_id, state.model_dump_json()),
        )


def save_lecture(state: LectureState) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE lectures SET state = %s WHERE id = %s",
            (state.model_dump_json(), state.lecture_id),
        )


def update_lecture_fields(lecture_id: str, **fields) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE lectures SET state = state || %s::jsonb WHERE id = %s",
            (json.dumps(fields), lecture_id),
        )


def delete_lecture(lecture_id: str, user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM lectures WHERE id = %s AND state->>'user_id' = %s",
            (lecture_id, user_id),
        )


def get_lecture(lecture_id: str) -> LectureState:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state FROM lectures WHERE id = %s", (lecture_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"No lecture found with id {lecture_id}")
        return LectureState.model_validate(row[0])


def list_subjects(user_id: str) -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT state->>'subject' AS subject FROM lectures WHERE state->>'user_id' = %s ORDER BY subject",
            (user_id,),
        ).fetchall()
        return [row[0] for row in rows]


def list_lectures(user_id: str, subject: str | None = None) -> list[LectureSummary]:
    query = "SELECT id, state->>'user_id', state->>'subject', state->>'status', created_at FROM lectures WHERE state->>'user_id' = %s"
    params = [user_id]
    if subject is not None:
        query += " AND state->>'subject' = %s"
        params.append(subject)
    query += " ORDER BY created_at DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [
            LectureSummary(
                lecture_id=str(row[0]),
                user_id=row[1],
                subject=row[2],
                status=row[3],
                created_at=row[4],
            )
            for row in rows
        ]