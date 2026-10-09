from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from apps.auth_service.auth import hash_password, verify_password, set_auth_cookie, clear_auth_cookie
from apps.auth_service.users_db import create_user, get_user_by_email, update_password, EmailAlreadyRegistered
from packages.shared_auth.jwt import get_current_user_id

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://web-pi-flax-71.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    email: str
    new_password: str
    confirm_password: str


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/auth/signup")
def signup_route(body: SignupRequest, response: Response):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    try:
        user_id = create_user(body.email.lower(), hash_password(body.password))
    except EmailAlreadyRegistered:
        raise HTTPException(status_code=409, detail="Email already registered")

    set_auth_cookie(response, user_id)
    return {"status": "ok"}


@app.post("/auth/login")
def login_route(body: LoginRequest, response: Response):
    user = get_user_by_email(body.email.lower())
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    set_auth_cookie(response, user["id"])
    return {"status": "ok"}


@app.post("/auth/reset-password")
def reset_password_route(body: ResetPasswordRequest):
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    updated = update_password(body.email.lower(), hash_password(body.new_password))
    if not updated:
        raise HTTPException(status_code=404, detail="No account found with that email")

    return {"status": "ok"}


@app.post("/auth/logout")
def logout_route(response: Response):
    clear_auth_cookie(response)
    return {"status": "ok"}


@app.get("/auth/me")
def me_route(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}
