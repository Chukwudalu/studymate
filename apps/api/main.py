import uuid
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from packages.shared_types.schemas import LectureState
from apps.api.auth import get_current_user_id, hash_password, verify_password, set_auth_cookie, clear_auth_cookie
from apps.api.db import create_lecture, get_lecture, update_lecture_fields, list_subjects, list_lectures, delete_lecture
from apps.api.users_db import create_user, get_user_by_email, update_password, EmailAlreadyRegistered
from apps.api.queue import enqueue_job

import os
import boto3
from botocore.client import Config

s3 = boto3.client(
    "s3",
    region_name="us-west-2",
    endpoint_url="https://s3.us-west-2.amazonaws.com",
    config=Config(signature_version="s3v4"),
)
S3_BUCKET = os.environ["S3_BUCKET"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://web-pi-flax-71.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


class CreateLectureRequest(BaseModel):
    audio_key: str
    subject: str


class GenerateFlashcardsRequest(BaseModel):
    count: int = 10


class GenerateQuizRequest(BaseModel):
    count: int = 10


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


def _get_owned_lecture(lecture_id: str, user_id: str) -> LectureState:
    try:
        state = get_lecture(lecture_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Lecture not found")

    if state.user_id != user_id:
        # Same response as "doesn't exist" - don't reveal other users' lectures exist.
        raise HTTPException(status_code=404, detail="Lecture not found")

    return state


@app.post("/lectures")
def create_lecture_route(body: CreateLectureRequest, user_id: str = Depends(get_current_user_id)):
    lecture_id = str(uuid.uuid4())
    state = LectureState(
        lecture_id=lecture_id,
        user_id=user_id,
        subject=body.subject,
        status="queued",
        audio_key=body.audio_key,
        raw_chunks=[],
    )
    create_lecture(state)
    enqueue_job("transcription", lecture_id)
    return {"lecture_id": lecture_id}


@app.get("/subjects")
def list_subjects_route(user_id: str = Depends(get_current_user_id)):
    return list_subjects(user_id)


@app.get("/lectures")
def list_lectures_route(subject: str | None = None, user_id: str = Depends(get_current_user_id)):
    return list_lectures(user_id, subject=subject)


@app.get("/lectures/{lecture_id}")
def get_lecture_route(lecture_id: str, user_id: str = Depends(get_current_user_id)):
    return _get_owned_lecture(lecture_id, user_id)


@app.delete("/lectures/{lecture_id}")
def delete_lecture_route(lecture_id: str, user_id: str = Depends(get_current_user_id)):
    state = _get_owned_lecture(lecture_id, user_id)

    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=state.audio_key)
    except Exception:
        pass

    delete_lecture(lecture_id, user_id)
    return {"status": "deleted"}


@app.post("/lectures/{lecture_id}/flashcards")
def generate_flashcards_route(lecture_id: str, body: GenerateFlashcardsRequest, user_id: str = Depends(get_current_user_id)):
    _get_owned_lecture(lecture_id, user_id)

    update_lecture_fields(lecture_id, flashcards_status="queued", flashcards_count=body.count)
    enqueue_job("flashcards", lecture_id)
    return {"status": "queued"}


@app.post("/lectures/{lecture_id}/quiz")
def generate_quiz_route(lecture_id: str, body: GenerateQuizRequest, user_id: str = Depends(get_current_user_id)):
    _get_owned_lecture(lecture_id, user_id)

    update_lecture_fields(lecture_id, quiz_status="queued", quiz_count=body.count)
    enqueue_job("quiz", lecture_id)
    return {"status": "queued"}


@app.post("/uploads/presign")
def presign_upload(user_id: str = Depends(get_current_user_id)):
    audio_key = f"lectures/{uuid.uuid4()}.mp3"

    upload_url = s3.generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": S3_BUCKET, "Key": audio_key},
        ExpiresIn=3600,
    )

    return {"upload_url": upload_url, "audio_key": audio_key}
