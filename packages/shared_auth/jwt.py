import os

import jwt
from fastapi import HTTPException, Request

# Pure JWT verification only - no password hashing, no cookie-setting. Kept
# separate from auth-service's own auth.py so core-api can depend on "verify
# a token" without pulling in signup/login logic it has no business doing.
AUTH_JWT_SECRET = os.environ["AUTH_JWT_SECRET"]
COOKIE_NAME = "studymate_token"


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
