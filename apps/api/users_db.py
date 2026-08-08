import uuid

import psycopg.errors

from apps.api.db import get_connection


class EmailAlreadyRegistered(Exception):
    pass


def create_user(email: str, password_hash: str) -> str:
    user_id = str(uuid.uuid4())
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (id, email, password_hash) VALUES (%s, %s, %s)",
                (user_id, email, password_hash),
            )
    except psycopg.errors.UniqueViolation:
        raise EmailAlreadyRegistered(email)
    return user_id


def get_user_by_email(email: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s", (email,)
        ).fetchone()
        if row is None:
            return None
        return {"id": str(row[0]), "email": row[1], "password_hash": row[2]}
