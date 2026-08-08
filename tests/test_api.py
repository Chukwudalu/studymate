import jwt
import pytest
from fastapi.testclient import TestClient

from apps.api import main
from packages.shared_types.schemas import LectureState, LectureSummary

USER_ID = "11111111-1111-1111-1111-111111111111"
OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"


def make_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id, "aud": "authenticated"}, "test-jwt-secret", algorithm="HS256")


@pytest.fixture
def client():
    return TestClient(main.app, cookies={"studymate_token": make_token(USER_ID)})


def make_state(**overrides):
    defaults = dict(
        lecture_id="lec-1",
        user_id=USER_ID,
        subject="Biology 201",
        status="done",
        audio_key="lectures/lec-1.mp3",
        raw_chunks=[],
    )
    defaults.update(overrides)
    return LectureState(**defaults)


def test_requests_without_token_are_rejected(monkeypatch):
    monkeypatch.setattr(main, "list_subjects", lambda user_id: [])
    unauthenticated_client = TestClient(main.app)

    res = unauthenticated_client.get("/subjects")

    assert res.status_code == 401


def test_requests_with_invalid_token_are_rejected(monkeypatch):
    monkeypatch.setattr(main, "list_subjects", lambda user_id: [])
    bad_token_client = TestClient(main.app, cookies={"studymate_token": "not-a-real-token"})

    res = bad_token_client.get("/subjects")

    assert res.status_code == 401


def test_requests_with_wrong_signature_are_rejected(monkeypatch):
    monkeypatch.setattr(main, "list_subjects", lambda user_id: [])
    forged_token = jwt.encode({"sub": USER_ID, "aud": "authenticated"}, "wrong-secret", algorithm="HS256")
    forged_client = TestClient(main.app, cookies={"studymate_token": forged_token})

    res = forged_client.get("/subjects")

    assert res.status_code == 401


def test_create_lecture(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "create_lecture", lambda state: captured.update(state=state))
    enqueued = {}
    monkeypatch.setattr(
        main, "enqueue_job", lambda job_type, lecture_id: enqueued.update(job_type=job_type, lecture_id=lecture_id)
    )

    res = client.post("/lectures", json={"audio_key": "lectures/x.mp3", "subject": "Biology 201"})

    assert res.status_code == 200
    lecture_id = res.json()["lecture_id"]
    assert enqueued == {"job_type": "transcription", "lecture_id": lecture_id}
    assert captured["state"].user_id == USER_ID


def test_get_lecture_found(client, monkeypatch):
    state = make_state()
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: state)

    res = client.get("/lectures/lec-1")

    assert res.status_code == 200
    assert res.json()["lecture_id"] == "lec-1"


def test_get_lecture_not_found(client, monkeypatch):
    def raise_not_found(lecture_id):
        raise ValueError("no such lecture")

    monkeypatch.setattr(main, "get_lecture", raise_not_found)

    res = client.get("/lectures/missing")

    assert res.status_code == 404


def test_get_lecture_owned_by_another_user_is_hidden(client, monkeypatch):
    state = make_state(user_id=OTHER_USER_ID)
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: state)

    res = client.get("/lectures/lec-1")

    assert res.status_code == 404


def test_delete_lecture_removes_s3_object_and_db_row(client, monkeypatch):
    state = make_state()
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: state)

    deleted_s3 = {}
    monkeypatch.setattr(
        main.s3, "delete_object", lambda Bucket, Key: deleted_s3.update(Bucket=Bucket, Key=Key)
    )
    deleted_db = {}
    monkeypatch.setattr(
        main, "delete_lecture", lambda lecture_id, user_id: deleted_db.update(lecture_id=lecture_id, user_id=user_id)
    )

    res = client.delete("/lectures/lec-1")

    assert res.status_code == 200
    assert deleted_s3 == {"Bucket": "test-bucket", "Key": "lectures/lec-1.mp3"}
    assert deleted_db == {"lecture_id": "lec-1", "user_id": USER_ID}


def test_delete_lecture_not_found(client, monkeypatch):
    def raise_not_found(lecture_id):
        raise ValueError("no such lecture")

    monkeypatch.setattr(main, "get_lecture", raise_not_found)

    res = client.delete("/lectures/missing")

    assert res.status_code == 404


def test_delete_lecture_owned_by_another_user_is_rejected(client, monkeypatch):
    state = make_state(user_id=OTHER_USER_ID)
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: state)
    deleted_db = {}
    monkeypatch.setattr(
        main, "delete_lecture", lambda lecture_id, user_id: deleted_db.update(lecture_id=lecture_id)
    )

    res = client.delete("/lectures/lec-1")

    assert res.status_code == 404
    assert deleted_db == {}


def test_delete_lecture_survives_s3_failure(client, monkeypatch):
    state = make_state()
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: state)

    def raise_s3_error(Bucket, Key):
        raise Exception("S3 is down")

    monkeypatch.setattr(main.s3, "delete_object", raise_s3_error)
    deleted_db = {}
    monkeypatch.setattr(
        main, "delete_lecture", lambda lecture_id, user_id: deleted_db.update(lecture_id=lecture_id)
    )

    res = client.delete("/lectures/lec-1")

    assert res.status_code == 200
    assert deleted_db == {"lecture_id": "lec-1"}


def test_generate_flashcards_queues_job(client, monkeypatch):
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: make_state())
    updated = {}
    monkeypatch.setattr(main, "update_lecture_fields", lambda lecture_id, **fields: updated.update(lecture_id=lecture_id, **fields))
    enqueued = {}
    monkeypatch.setattr(
        main, "enqueue_job", lambda job_type, lecture_id: enqueued.update(job_type=job_type, lecture_id=lecture_id)
    )

    res = client.post("/lectures/lec-1/flashcards", json={"count": 15})

    assert res.status_code == 200
    assert updated == {"lecture_id": "lec-1", "flashcards_status": "queued", "flashcards_count": 15}
    assert enqueued == {"job_type": "flashcards", "lecture_id": "lec-1"}


def test_generate_flashcards_not_found(client, monkeypatch):
    def raise_not_found(lecture_id):
        raise ValueError("no such lecture")

    monkeypatch.setattr(main, "get_lecture", raise_not_found)

    res = client.post("/lectures/missing/flashcards", json={"count": 10})

    assert res.status_code == 404


def test_generate_flashcards_owned_by_another_user_is_rejected(client, monkeypatch):
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: make_state(user_id=OTHER_USER_ID))
    enqueued = {}
    monkeypatch.setattr(main, "enqueue_job", lambda job_type, lecture_id: enqueued.update(job_type=job_type))

    res = client.post("/lectures/lec-1/flashcards", json={"count": 10})

    assert res.status_code == 404
    assert enqueued == {}


def test_generate_quiz_queues_job(client, monkeypatch):
    monkeypatch.setattr(main, "get_lecture", lambda lecture_id: make_state())
    updated = {}
    monkeypatch.setattr(main, "update_lecture_fields", lambda lecture_id, **fields: updated.update(lecture_id=lecture_id, **fields))
    enqueued = {}
    monkeypatch.setattr(
        main, "enqueue_job", lambda job_type, lecture_id: enqueued.update(job_type=job_type, lecture_id=lecture_id)
    )

    res = client.post("/lectures/lec-1/quiz", json={"count": 7})

    assert res.status_code == 200
    assert updated == {"lecture_id": "lec-1", "quiz_status": "queued", "quiz_count": 7}
    assert enqueued == {"job_type": "quiz", "lecture_id": "lec-1"}


def test_list_subjects(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "list_subjects", lambda user_id: (captured.update(user_id=user_id), ["Biology 201", "Chemistry 101"])[1])

    res = client.get("/subjects")

    assert res.status_code == 200
    assert res.json() == ["Biology 201", "Chemistry 101"]
    assert captured["user_id"] == USER_ID


def test_list_lectures_with_subject_filter(client, monkeypatch):
    captured = {}

    def fake_list_lectures(user_id, subject=None):
        captured["user_id"] = user_id
        captured["subject"] = subject
        return [
            LectureSummary(
                lecture_id="lec-1",
                user_id=USER_ID,
                subject="Biology 201",
                status="done",
                created_at="2026-08-01T00:00:00Z",
            )
        ]

    monkeypatch.setattr(main, "list_lectures", fake_list_lectures)

    res = client.get("/lectures", params={"subject": "Biology 201"})

    assert res.status_code == 200
    assert captured["subject"] == "Biology 201"
    assert captured["user_id"] == USER_ID
    assert res.json()[0]["lecture_id"] == "lec-1"


def test_presign_upload(client, monkeypatch):
    monkeypatch.setattr(
        main.s3,
        "generate_presigned_url",
        lambda ClientMethod, Params, ExpiresIn: "https://example-presigned-url",
    )

    res = client.post("/uploads/presign")

    assert res.status_code == 200
    body = res.json()
    assert body["upload_url"] == "https://example-presigned-url"
    assert body["audio_key"].startswith("lectures/") and body["audio_key"].endswith(".mp3")


def test_presign_upload_requires_auth():
    unauthenticated_client = TestClient(main.app)

    res = unauthenticated_client.post("/uploads/presign")

    assert res.status_code == 401
