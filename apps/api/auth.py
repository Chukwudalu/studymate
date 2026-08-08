import os
import time
import uuid

import bcrypt
import jwt
from fastapi import HTTPException, Request, Response

AUTH_JWT_SECRET = os.environ["AUTH_JWT_SECRET"]
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

COOKIE_NAME = "studymate_token"
# Cookies need Secure (HTTPS-only) + SameSite=None to be sent cross-site (Vercel -> API
# Gateway). Locally, uvicorn runs over plain HTTP, which browsers refuse to set Secure
# cookies over - so this is relaxed for local dev via COOKIE_SECURE=false in .env.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "aud": "authenticated",
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, AUTH_JWT_SECRET, algorithm="HS256")


def set_auth_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_access_token(user_id),
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE)


def get_current_user_id(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")

    try:
        payload = jwt.decode(
            token,
            AUTH_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return payload["sub"]
