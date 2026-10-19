# Rebuild Spec: Lecture Notes App on Vercel + Railway (no AWS)

**How to use this file.** You are a Claude Code session starting a brand-new
project. This document is a complete specification of an existing app (called
"StudyMate" in the original) and a plan to rebuild it as a **simple, cheap,
production deployment**: React frontend on **Vercel**, a **single FastAPI
monolith** on **Railway**, **Supabase Postgres** for data, and **no AWS**.

You do **not** have access to the original repo, so everything you need is
here: data model, API contract, prompts (verbatim), pipeline logic, frontend
behaviour, and the mistakes already made. Where this spec says
"decision", it is deliberate: don't re-litigate it without a concrete reason.
Where it says "verify", check the current docs before relying on it (model
names and library versions drift).

The original ran on AWS (Lambda, ECS, SQS, S3, then an EKS migration) purely
as a portfolio exercise. **This rebuild is the real product for real users.**
Optimise for: cheap, simple, hard to abuse, easy to operate alone.

---

## 1. What the product does

A student records or uploads a lecture. The app transcribes it, splits it by
topic, writes notes, and then on demand generates flashcards, a multiple-choice
quiz, and a chat assistant that answers questions from the notes.

User flow:
1. Sign up / sign in (email + password).
2. Pick or create a **subject** (free-text label, e.g. "Biology 201").
3. **Upload an audio file** or **record in the browser** (mic).
4. Lecture appears at `/lecture/:id` with a live status pill; page polls every 3s.
   Status: `queued → transcribing → segmenting → generating_notes → done` (or `failed`).
5. When `done`: notes (per topic segment: summary + key terms) are shown.
   User can generate **flashcards** (count 1-100, default 10), a **quiz**
   (count 1-100, default 10), and **chat** with the notes.
6. Sidebar lists subjects; a subject page lists its lectures grouped by date.
7. Delete a lecture (also deletes its audio).
8. Sign out; password reset (see the security warning in section 12 — the
   original implementation is unsafe and must NOT be copied).

---

## 2. Target architecture

```
Browser ──► Vercel (React/Vite static SPA)
   │
   └──► Railway: ONE FastAPI service ("api")  ──► Supabase Postgres
            │  ├─ HTTP API (auth, lectures, uploads, chat)
            │  └─ background worker loop (same process or 2nd Railway service)
            ├──► Supabase Storage  (audio files; signed upload URLs)
            ├──► OpenAI  (Whisper transcription)
            └──► Anthropic (segmentation, notes, flashcards, quiz, chat)
```

Decisions:

| Topic | Decision | Why |
|---|---|---|
| Backend shape | **One FastAPI monolith** (auth + lectures + uploads + chat + worker) | The original was split into 3 microservices only for a Kubernetes exercise. At this scale it is pure overhead. |
| Queue | **Postgres table** (`jobs`) claimed with `FOR UPDATE SKIP LOCKED` | Replaces SQS. No extra service, survives restarts, retries are easy. See §7. |
| Audio storage | **Supabase Storage** (private bucket, signed upload URL, browser PUTs directly) | Replaces S3 with the same presign flow, and keeps one vendor. Alternative: Cloudflare R2 (S3-compatible, `boto3` works, generous free tier). |
| Worker | In the same container as a background thread/async task pool **or** a second Railway service from the same image with a different start command | Start with one service. Split if CPU-heavy transcription starves the API. |
| Frontend ↔ API | Direct cross-origin calls, with both on **subdomains of one registrable domain** | e.g. `app.example.com` (Vercel) and `api.example.com` (Railway). Same *site* ⇒ cookies work with `SameSite=Lax`, no third-party-cookie problems. |
| Auth | Own email+password, bcrypt, signed JWT in an **httpOnly cookie** | Keep (it works), but fix the reset flow (§12). Alternative: Supabase Auth — a legitimate simplification if you'd rather not own passwords. |
| Secrets | Railway/Vercel environment variables | Nothing fancy needed. |
| CI/CD | Railway auto-deploy from GitHub + Vercel auto-deploy | No pipeline to maintain. Run tests in a small GitHub Action. |

Estimated running cost: Railway ≈ $5-10/month, Vercel + Supabase free tiers,
plus per-use AI costs (Whisper ≈ $0.006/audio-minute; Anthropic for notes/
flashcards/quiz/chat). **AI usage is the real cost risk — see §12.**

---

## 3. Tech stack

Backend (Python 3.13): `fastapi`, `uvicorn[standard]`, `psycopg[binary]` (v3,
direct Postgres, no ORM), `pydantic` v2, `pyjwt`, `bcrypt`, `openai`,
`langchain-anthropic` + `langgraph` (the original used LangGraph for the three
pipelines; for a monolith, plain sequential Python functions are simpler and
equally good — your call), `pydub` + system **ffmpeg**, `audioop-lts`
(pydub needs it on Python 3.13), `python-dotenv`, `supabase` or `httpx`
(Storage REST), `pytest`, `httpx` (TestClient).
Original pins for reference: fastapi 0.140.7, psycopg 3.3.4, pydantic 2.13.4,
pyjwt 2.13.0, bcrypt 5.0.0, openai 2.48.0, langchain-anthropic 1.5.1,
langgraph 1.2.9, pydub 0.25.1. **Verify and use current versions.**

Frontend: React 19, `react-router-dom` 7, TypeScript, Vite, plain CSS (a single
`index.css`, no UI framework), `oxlint`. No state library: component state +
a small `AuthContext`.

Models (original values — **verify current model IDs before use**):
transcription `whisper-1` (OpenAI), everything else Anthropic
`claude-sonnet-5` via `ChatAnthropic(model_name=..., timeout=...)`.

---

## 4. Suggested repo layout

```
app/
  main.py            # FastAPI app, CORS, routers
  config.py          # env vars
  auth.py            # bcrypt + JWT cookie helpers, get_current_user_id dependency
  db.py              # psycopg helpers (see §5)
  routes/            # auth.py, lectures.py, uploads.py, chat.py
  storage.py         # Supabase Storage: signed upload URL, download, delete
  jobs.py            # enqueue + claim + worker loop (see §7)
  pipeline/          # transcribe.py, segment.py, notes.py, flashcards.py, quiz.py, prompts.py
  schemas.py         # pydantic models (section 6)
tests/
Dockerfile           # python:3.13-slim + ffmpeg  (see §10)
web/                 # Vite React app
```

---

## 5. Database (Postgres on Supabase)

The original used two tables, hand-created in the Supabase SQL editor (the
schema was never in the repo, which is why it's written out here). Lecture
data lives in **one JSONB column** — convenient, but see the improvement note.

```sql
create table users (
  id            uuid primary key default gen_random_uuid(),
  email         text not null unique,
  password_hash text not null,
  created_at    timestamptz not null default now()
);

create table lectures (
  id         uuid primary key,
  state      jsonb not null,            -- the whole LectureState (section 6)
  created_at timestamptz default now()
);
```

**Recommended improvements for the rebuild** (the original filtered with
`state->>'user_id'` and had no index — fine at 10 rows, not at 10,000):

```sql
create table lectures (
  id         uuid primary key,
  user_id    uuid not null references users(id) on delete cascade,
  subject    text not null,
  status     text not null,
  state      jsonb not null,            -- keep the rest as JSONB
  created_at timestamptz not null default now()
);
create index lectures_user_created on lectures (user_id, created_at desc);
create index lectures_user_subject on lectures (user_id, subject);

create table jobs (                      -- the queue, see section 7
  id           bigserial primary key,
  job_type     text not null check (job_type in ('transcription','flashcards','quiz')),
  lecture_id   uuid not null references lectures(id) on delete cascade,
  status       text not null default 'queued',   -- queued | running | done | failed
  attempts     int  not null default 0,
  max_attempts int  not null default 3,
  run_after    timestamptz not null default now(),
  locked_at    timestamptz,
  last_error   text,
  created_at   timestamptz not null default now()
);
create index jobs_claim on jobs (status, run_after);
```

If you keep `state` as the source of truth for status, keep the status
column in sync (or just drop the column and keep the original approach).

**Security (important on Supabase):** every table in the `public` schema is
exposed through Supabase's auto-generated REST API to the `anon` and
`authenticated` roles. The original had RLS **off** on `users` and the `anon`
role held full privileges on it — the password hashes were readable/writable to
anyone holding the project's anon key. Since this backend connects directly
with the `postgres` role (which bypasses RLS) and the frontend never talks to
Supabase directly, lock everything down:

```sql
alter table users   enable row level security;
alter table lectures enable row level security;
alter table jobs    enable row level security;
revoke all on users, lectures, jobs from anon, authenticated;
```
(No policies = no access for those roles; the backend is unaffected.)

Connection: use Supabase's **pooler** connection string (port 6543,
transaction mode) from Railway. The original opened a **new connection per
call** (`psycopg.connect(DATABASE_URL)` in a `with`), which is simple and fine
for this load; a small pool (`psycopg_pool`) is a reasonable upgrade.
With the transaction pooler, avoid server-side prepared statements
(`prepare_threshold=None`) — verify against current psycopg/Supabase docs.

Two query patterns from the original worth keeping:

```sql
-- partial update without read-modify-write: merge top-level keys of state
UPDATE lectures SET state = state || %s::jsonb WHERE id = %s;

-- atomic chat append (two concurrent sends can't clobber each other),
-- scoped to the owner
UPDATE lectures
SET state = jsonb_set(state, '{chat_messages}',
      COALESCE(state->'chat_messages', '[]'::jsonb) || %s::jsonb)
WHERE id = %s AND state->>'user_id' = %s
RETURNING state;
```

---

## 6. Data models (pydantic — reproduce exactly)

```python
class RawChunk(BaseModel):   text: str; start_ms: int; end_ms: int
class Segment(BaseModel):    id: str; start_ms: int; end_ms: int; text: str; topic_label: str | None = None
class NoteBlock(BaseModel):  segment_id: str; summary: str; key_terms: list[str]; rolling_context_used: str | None = None
class Flashcard(BaseModel):  id: str; front: str; back: str; source_segment_id: str; difficulty: Literal["easy","medium","hard"] | None = None
class QuizQuestion(BaseModel): id: str; question: str; choices: list[str]; correct_option: str; explanation: str; source_segment_id: str
class ChatMessage(BaseModel): role: Literal["user","assistant"]; content: str
class LectureSummary(BaseModel): lecture_id: str; user_id: str; subject: str; status: str; created_at: datetime

class LectureState(BaseModel):
    lecture_id: str
    user_id: str
    subject: str
    status: Literal["queued","transcribing","segmenting","generating_notes","done","failed"]
    flashcards_status: Literal["not requested","queued","generating","done","failed"] = "not requested"
    quiz_status:       Literal["not requested","queued","generating","done","failed"] = "not requested"
    raw_transcript: str | None = None
    raw_chunks: list[RawChunk]
    audio_key: str
    flashcards_count: int = 10
    quiz_count: int = 10
    segments: list[Segment] = []
    notes: list[NoteBlock] = []
    flashcards: list[Flashcard] = []
    quiz: list[QuizQuestion] = []
    chat_messages: list[ChatMessage] = []
    transcription_errors: list[str] = []
    flashcards_errors: list[str] = []
    quiz_errors: list[str] = []
```
The frontend has an identical TypeScript mirror (`types.ts`); keep them in sync.
`GET /lectures/{id}` returns the whole `LectureState` (including transcript
and chunks — large; consider trimming `raw_chunks` from the response).

---

## 7. Jobs and the worker (replaces SQS)

Job types: `transcription`, `flashcards`, `quiz`. Original message body:
`{"job_type": "...", "lecture_id": "..."}`.

**Enqueue:** `INSERT INTO jobs (job_type, lecture_id) VALUES (...)`.

**Claim (worker loop, e.g. every 1-2 s when idle):**
```sql
UPDATE jobs SET status='running', locked_at=now(), attempts=attempts+1
WHERE id = (
  SELECT id FROM jobs
  WHERE (status='queued' AND run_after <= now())
     OR (status='running' AND locked_at < now() - interval '15 minutes')  -- crashed worker
  ORDER BY id
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```
**Complete:** `status='done'`. **Fail:** if `attempts < max_attempts`, set
`status='queued'`, `run_after = now() + interval '30 seconds' * attempts`,
`last_error`; else `status='failed'`.

Behaviour to preserve (hard-won):
- A pipeline failure **marks the lecture/artifact `failed` and stores the error
  string** in `transcription_errors` / `flashcards_errors` / `quiz_errors`
  (the UI shows them), then re-raises so the queue can retry.
- The original used SQS with a 15-minute visibility timeout and 3 receives
  before a dead-letter queue. **Side effect worth fixing:** a failing job kept
  retrying for ~45 minutes. Retry only transient errors (network/5xx/rate
  limit); a "file not found" or a 4xx account/quota error should fail fast.
- Concurrency: the original raised worker concurrency so several users could
  process at once. Start with 2 concurrent jobs; transcription is the heavy one
  (I/O to OpenAI + ffmpeg CPU).
- Make the worker log with unbuffered stdout (`PYTHONUNBUFFERED=1`), or you
  won't see logs until the process exits.

---

## 8. API contract

All JSON. Auth = httpOnly cookie (§9). `401 {"detail": "Not signed in"}` or
`"Invalid or expired session"` when missing/invalid. Lecture endpoints return
**404 "Lecture not found"** both when the id doesn't exist and when it belongs
to someone else (don't reveal other users' lecture ids).

| Method & path | Body | Result |
|---|---|---|
| `POST /auth/signup` | `{email, password}` | 400 if password < 8 chars; 409 `"Email already registered"`; sets cookie; `{"status":"ok"}`. Emails lower-cased. |
| `POST /auth/login` | `{email, password}` | 401 `"Invalid email or password"` (same message for unknown email and wrong password); sets cookie. |
| `POST /auth/logout` | – | clears cookie. |
| `GET /auth/me` | – | `{"user_id": "..."}`; the frontend uses 200/401 as "am I signed in". |
| `POST /auth/reset-password` | – | **Redesign — see §12. Do not copy the original.** |
| `GET /subjects` | – | `["Biology 201", ...]` distinct, sorted. |
| `GET /lectures?subject=` | – | `LectureSummary[]`, newest first. |
| `POST /uploads/presign` | – | `{upload_url, audio_key}`; key is `lectures/{uuid}.<ext>`. Original hard-coded `.mp3` for every upload even when the bytes were webm/ogg/m4a — ffmpeg sniffs content so it worked, but use the real extension/content type. |
| `POST /lectures` | `{audio_key, subject}` | creates lecture with `status="queued"`, enqueues `transcription`; `{lecture_id}`. |
| `GET /lectures/{id}` | – | full `LectureState`. |
| `DELETE /lectures/{id}` | – | deletes audio (ignore errors) then the row; `{"status":"deleted"}`. |
| `POST /lectures/{id}/flashcards` | `{count}` | sets `flashcards_status="queued"`, `flashcards_count`; enqueues; `{"status":"queued"}`. |
| `POST /lectures/{id}/quiz` | `{count}` | same for quiz. |
| `POST /lectures/{id}/chat` | `{message}` | 400 `"Notes aren't ready yet for this lecture"` if no notes; answers from notes + history; appends both messages atomically; returns `{chat_messages: [...all]}`. Synchronous, ~25 s LLM timeout. |
| `GET /healthz` | – | `{"status":"ok"}` (for Railway health checks). |

CORS: allow the exact frontend origin(s) (e.g. `https://app.example.com`,
`http://localhost:5173`), `allow_credentials=True`, all methods/headers.
**Never use `*` with credentials.**

Upload flow (browser): `POST /uploads/presign` → `PUT` the file to
`upload_url` (storage CORS must allow the frontend origin and `PUT`) →
`POST /lectures`.

---

## 9. Auth details

- Passwords: `bcrypt.hashpw(pw, gensalt())`; verify with `bcrypt.checkpw`.
- Token: HS256 JWT, claims `sub` (user id), `aud="authenticated"`, `iat`,
  `exp` (7 days), `jti` (uuid). Secret in env (`AUTH_JWT_SECRET`, 64+ random chars).
  Decode with `algorithms=["HS256"], audience="authenticated"`.
- Cookie: httpOnly, `path="/"`, `max_age` = 7 days, name your own (original
  `studymate_token`). Flags:
  - **Production:** `Secure=True`. With frontend and API on subdomains of the
    same domain, `SameSite=Lax` is enough and the safest.
  - If you ever serve the frontend from a *different* site (e.g. a raw
    `*.vercel.app` URL calling `api.example.com`), you need
    `SameSite=None; Secure`, and browsers' third-party-cookie restrictions may
    still break it. **Avoid by using one domain.**
  - Local dev over plain HTTP: `Secure` cookies are refused, so the original
    used an env switch `COOKIE_SECURE=false` → `SameSite=Lax`.
- Frontend sends `fetch(..., {credentials: "include"})` on every call. The
  token is never visible to JS.
- Add CSRF consideration: with `SameSite=Lax` cookie and JSON bodies this is
  acceptable; keep state-changing routes POST/DELETE only.

---

## 10. The pipeline (the actual product value) — reproduce faithfully

### 10.1 Transcription — `status = "transcribing"`
1. Download the audio from storage to a temp file.
2. `AudioSegment.from_file(path)` (pydub → needs **ffmpeg**).
3. Split into **20-minute chunks** (`MAX_CHUNK_MS = 20*60*1000`) — keeps each
   export under Whisper's **25 MB** upload limit. Export each chunk as mp3.
4. For each chunk call OpenAI:
   `client.audio.transcriptions.create(model="whisper-1", file=f,
   response_format="verbose_json", timestamp_granularities=["segment"])`
   with `OpenAI(timeout=300)`.
5. For each returned segment build a `RawChunk(text, start_ms, end_ms)` where
   times are `offset_ms + int(seg.start*1000)`; after each chunk,
   `offset_ms += len(chunk_audio)`.
6. `raw_transcript = " ".join(chunk.text)`; store `raw_chunks`.
7. **Improvements:** delete temp files; delete the stored audio once
   transcription succeeds (privacy + storage cost); reject files > N minutes
   up front (§12); reject silent audio.

### 10.2 Segmentation — `status = "segmenting"`
Number the chunks `[0] text`, `[1] text`... and ask the LLM which indices
start a new topic, with structured output `TopicBoundaries(boundary_chunk_indices: list[int])`.
`boundaries = sorted(set(indices) | {0}) + [len(chunks)]`; each consecutive pair
becomes `Segment(id=f"seg_{i}", start_ms=first.start_ms, end_ms=last.end_ms,
text=" ".join(texts))`. Model timeout 120 s.

Prompt (verbatim):
```
You are given a numbered list of transcript chunks from a lecture.
Identify which chunk indices mark the START of a new topic (a meaningful shift in subject matter).
Always include index 0.
Return only the chunk indices where a new topic begins — not every chunk.

Transcript chunks:
{numbered_chunks}
```
(Guard against an empty transcript and against an LLM returning out-of-range
indices — the original didn't.)

### 10.3 Notes — `status = "generating_notes"`, then `"done"`
Process segments **sequentially** carrying a rolling summary. Structured
output `NoteOutput(summary: str, key_terms: list[str], updated_rolling_summary: str)`.
For each segment: call with `rolling_context` (empty string for the first),
store `NoteBlock(segment_id, summary, key_terms, rolling_context_used=rolling_context)`,
then `rolling_context = result.updated_rolling_summary`.

Prompt (verbatim):
```
You are summarizing a lecture, one topic segment at a time.

Here is what has been covered so far in the lecture (empty if this is the first segment):
{rolling_context}

Here is the next segment's raw transcript text:
{segment_text}

Do three things:
1. Write a concise summary of THIS segment only. Use the prior context above to correctly
   resolve any references to earlier material (e.g. "as I mentioned earlier", "going back to X").
2. List the key terms/concepts introduced or discussed in this segment, as short standalone phrases.
3. Write an updated rolling summary covering the ENTIRE lecture so far (prior context + this
   segment), to be passed forward as context when processing the next segment.
```
After the transcription job finishes, persist: `status`, `raw_transcript`,
`raw_chunks`, `segments`, `notes`, and clear `transcription_errors`.

### 10.4 Flashcards (on demand) — `flashcards_status = "generating"` → `"done"`
`count` is spread across notes with `distribute_count(total, parts)`:
`base = total // parts; remainder = total % parts;` first `remainder` parts get
`base+1`. Skip parts whose count is 0. Per note, structured output
`FlashcardsOutput(flashcards: list[FlashcardDraft(front, back, difficulty?)])`;
create `Flashcard(id=uuid4, ..., source_segment_id=note.segment_id)`.

```
You are creating study flashcards from a lecture note
summary of this part of the lecture:
{summary}

key terms covered:
{key_terms}

Generate exactly {count} flashcards testing understanding of this material. Each flashcard should have
a clear question/prompt on the front and a concise, accurate answer on the back. Avoid
trivial yes/no questions — favor questions that test real understanding of the concept.
```
**Gotcha (a real production bug):** the model sometimes returned the list
JSON-encoded as a string, wrapped in a dict (`{"flashcards": [...]}`), or a
**single unwrapped flashcard dict**. The original fixed it with a pydantic
`field_validator("flashcards", mode="before")` that: `json.loads` if a string;
if a dict, return `value["flashcards"]` if present, `[value]` if it has
`front` and `back`, else the dict. Keep an equivalent tolerant validator and a
unit test for each shape.

### 10.5 Quiz (on demand) — `quiz_status`
Same distribution logic. Structured output `QuizOutput(questions: list[QuizQuestionDraft(question, choices, correct_option, explanation)])`
with the same tolerant `before` validator (string → `json.loads`; dict →
`parsed.get("questions", parsed)`). Create `QuizQuestion(id=uuid4, ...,
source_segment_id)`.

```
You are creating multiple-choice quiz questions from a lecture note.

Summary of this part of the lecture:
{summary}

Key terms covered:
{key_terms}

Generate exactly {count} multiple-choice questions testing understanding of this material. Each question
should have exactly 4 choices. correct_option must be an exact copy of the correct choice's
text from the choices list — not a letter or index. Include a brief explanation of why the
correct answer is right. Avoid ambiguous questions or choices that are obviously wrong at a
glance — distractors should be plausible.
```
Validate after generation: `correct_option in choices` and `len(choices) == 4`;
regenerate or drop invalid questions.

### 10.6 Chat
Synchronous endpoint. Context is the notes only (summary + key terms), not the
raw transcript. Prompt (verbatim), timeout 25 s:
```
You are a helpful study assistant answering a student's question about their lecture notes.

Only answer using the notes below. If the answer isn't covered in the notes, say so plainly instead of guessing.

Lecture notes:
{notes_context}
{history_block}
Student's question:
{question}
```
- `notes_context` = `"\n\n".join(f"- {n.summary}\n  Key terms: {', '.join(n.key_terms)}" for n in notes)`
- `history_block` = `""` if no history else `"\nConversation so far:\n" + "\n".join(f"{role}: {content}") + "\n"`
- If the LLM returns a list of content blocks, join only blocks with
  `type == "text"`; if a string, use it as-is.
- Hard-cap history length sent to the model (the original sent all of it).

### 10.7 Dockerfile (backend)
```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```
Railway injects `$PORT`; set the health check path to `/healthz`.

---

## 11. Frontend (Vercel)

Vite + React 19 + TypeScript + react-router. **Routes:**
`/` Upload page · `/subject/:name` Subject page · `/lecture/:id` Lecture
detail · sign-in screen when unauthenticated (the original used a
`RequireAuth` wrapper + `AuthContext` that calls `GET /auth/me`).
(Client routes are singular — `/subject`, `/lecture` — deliberately distinct
from API paths `/subjects`, `/lectures`.)

Files and behaviour:
- `api.ts` — thin `fetch` wrapper with `credentials: "include"`; one function
  per endpoint; non-OK responses throw `Error(body.detail ?? "Request failed: ...")`.
  `API_URL = import.meta.env.VITE_API_URL`.
- `LoginPage` — one form with three modes: sign in / sign up / reset password.
- `Layout` — sidebar (logo, "+ New lecture", subjects list, sign out) + `<Outlet/>`.
  **Responsive (do this from the start):** under 768 px the sidebar becomes a
  sticky top bar with a Menu button and a slide-in drawer + scrim; drawer closes
  on route change and on scrim tap; use `100dvh`; inputs `font-size:16px`
  (stops iOS Safari zooming on focus); 44 px minimum tap targets; verify no
  horizontal overflow at 390 px.
- `UploadPage` — toggle **Upload a file** (`<input type=file accept="audio/*">`)
  vs **Record now**; subject `<select>` of existing subjects or "Add new
  subject" text input; "Upload & transcribe" → presign → PUT → create lecture →
  navigate to `/lecture/:id`.
- `AudioRecorder` — `getUserMedia({audio:true})` + `MediaRecorder`; timer; stop →
  preview in `<audio controls>` + "Re-record". **Hard-won details:**
  - Containers differ: Chrome/Edge record **webm**, Firefox **ogg/opus**, iOS
    Safari **mp4/m4a**. Choose the file extension from `recorder.mimeType`
    (`webm`/`ogg`/`m4a`) and pass the type through.
  - **Silent recordings happen** (muted mic, wrong default device, OS privacy
    setting, other app holding the mic). The original happily uploaded a
    minute of digital silence (-91 dB). Add a **live input meter** using
    `AudioContext` + `AnalyserNode` (`getByteTimeDomainData`, peak of
    `|v-128|/128`): show the level bar while recording; if the peak stays
    below ~0.01 after 3 s show a warning naming the device
    (`stream.getAudioTracks()[0].label`); on stop, if the overall peak is
    below ~0.003, **reject the recording** with an explanatory error instead
    of uploading it.
  - Playing a video on the same phone while recording won't work (echo
    cancellation strips it); test with a second device or by speaking.
- `LectureDetailPage` — header with status pill and Delete (confirm dialog);
  polls `GET /lectures/{id}` **every 3 s** until terminal state (ignore
  transient errors); shows notes when `status === "done"`, failure message when
  `failed`; flashcards and quiz sections each with a count input (1-100) and a
  Generate button disabled while `queued`/`generating`, and the stored errors if
  `failed`; `FlashcardView` (click-to-flip 3D card, front/back, difficulty tag);
  `QuizView` (4 options, reveal correct/wrong + explanation); `ChatPanel`
  (message bubbles, pending state, input row).
- `SubjectPage` — lectures for a subject grouped by date, each row a link with
  a status pill.
- Design: a calm green/neutral palette via CSS variables with
  `prefers-color-scheme: dark` support, serif display font (Iowan Old Style /
  Palatino / Georgia) for headings, system sans for UI.

Vercel config: project root = `web/`, framework Vite, env var
`VITE_API_URL=https://api.<yourdomain>` (set it in the Vercel project, not in a
committed file — dotenv files are usually gitignored and the Vercel setting
overrides them). Add a `vercel.json` SPA fallback so deep links work:
`{"rewrites":[{"source":"/(.*)","destination":"/index.html"}]}`.
**Do not proxy the API through Vercel rewrites** for this product: Vercel
limits proxied request bodies (~4.5 MB) and adds a hop. Call the API directly.

---

## 12. Production hardening (this is a public product — do these)

1. **Password reset is unsafe in the original — do not port it.** It accepted
   `{email, new_password, confirm_password}` and changed the password with **no
   proof of email ownership**, i.e. anyone could take over any account. Replace
   with a signed, single-use, short-lived reset token emailed to the user
   (Resend/Postmark/Supabase SMTP), or switch to Supabase Auth / magic links.
2. **Rate limiting** on `/auth/*` (credential stuffing, signup spam) and on
   expensive endpoints. A small in-memory/Redis limiter or a dependency like
   `slowapi` is enough to start.
3. **Cap AI cost per user.** Every lecture burns Whisper + several Anthropic
   calls; flashcards/quiz counts go up to 100. Enforce: max audio length and
   file size (check size at presign/upload and duration after download), a
   per-user daily/monthly minutes budget, max concurrent jobs per user, and cap
   `count` server-side (the frontend limit is not a control). Consider an
   invite list or waitlist at launch.
4. **Upload validation:** restrict content types/extensions, size limit on the
   signed URL (storage policy), and delete orphaned audio (uploaded but never
   turned into a lecture) with a periodic cleanup.
5. **Secrets hygiene:** never commit `.env`, DB URLs, or API keys; rotate any
   key that appears in a log or chat. Use separate keys per environment.
6. **Account/data deletion:** deleting a lecture should delete its audio;
   provide account deletion; state your data retention in a short privacy page.
7. Validate `subject` (length, trim); escape in UI (React does by default).
8. Don't expose internals: add a global exception handler that logs the
   traceback server-side and returns a generic message to the client.
9. Add Sentry (or Railway logs at minimum) and a `/healthz` uptime check.
10. Back up Postgres (Supabase daily backups on paid tier; otherwise a
    scheduled `pg_dump`).

---

## 13. Testing

The original had ~51 pytest tests using FastAPI `TestClient` with the DB, LLM,
and queue mocked. Cover at least: auth (signup validation, duplicate email,
wrong password, cookie flags, `me`), ownership (user B gets 404 on user A's
lecture), lecture create/delete, `distribute_count`, the tolerant flashcard and
quiz validators (string / wrapped dict / single dict / list), chat (notes not
ready → 400; history appended), job claim/retry logic, and the recorder's
silence rejection (a Playwright test with Chromium's fake mic flags
`--use-fake-ui-for-media-stream --use-fake-device-for-media-stream
--use-file-for-fake-audio-capture=silence.wav`).
CI: a GitHub Action running `pytest` and the frontend `tsc -b && vite build`.

---

## 14. Environment variables

Backend (Railway):
```
DATABASE_URL            # Supabase pooler URL
AUTH_JWT_SECRET         # 64+ random chars
OPENAI_API_KEY
ANTHROPIC_API_KEY
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY   # server-side only, never in the frontend
STORAGE_BUCKET              # private bucket name
FRONTEND_ORIGIN             # e.g. https://app.example.com  (CORS)
COOKIE_SECURE               # "true" in prod, "false" for local http
PYTHONUNBUFFERED=1
```
Frontend (Vercel): `VITE_API_URL`.

---

## 15. Deployment steps

1. **Supabase:** new project (do **not** reuse any database from the original);
   run the SQL in §5 including the RLS/revoke block; create a **private**
   Storage bucket; add a CORS rule allowing `PUT` from your frontend origin.
2. **Railway:** new project → deploy from the GitHub repo using the Dockerfile;
   set the env vars; health check `/healthz`; add custom domain
   `api.<yourdomain>` (Railway shows a CNAME target; Railway issues the TLS
   cert itself — no ACM/cert work needed).
3. **Vercel:** import the repo, root `web/`, set `VITE_API_URL`, add custom
   domain `app.<yourdomain>` (and optionally the apex).
4. **DNS** at the registrar (the author used Namecheap, Advanced DNS): one
   CNAME per subdomain pointing at the targets Railway and Vercel show you.
   Host field = the label only (`api`, `app`), not the full name. New `.ca`
   domains may need registrant-agreement verification before they resolve.
5. Smoke test: sign up → record 10 s of speech → watch status progress → notes
   appear → generate flashcards/quiz → chat → delete. Test on a real phone and
   on a second desktop browser (Firefox + Chromium).

---

## 16. Suggested build order

1. Repo, Dockerfile, `/healthz`, deploy an empty service to Railway + Vercel
   (prove the pipeline and DNS/cookies first, before any features).
2. DB schema + auth routes + cookie; login page; `RequireAuth`.
3. Upload flow (presign → storage → create lecture → enqueue).
4. Worker loop + transcription → segmentation → notes; lecture detail page with polling.
5. Flashcards, quiz, chat.
6. Recorder with level meter; responsive layout.
7. Hardening (§12), tests (§13), monitoring, then invite users.

## 17. Original-project facts that may help

- The original repo name/brand was "StudyMate"; rename freely (cookie name,
  UI strings, docs).
- It was built with Python 3.13 and psycopg 3 directly (no ORM) and Vite 8 /
  React 19 / TypeScript 6 on the frontend.
- A separate AWS (Lambda → EKS) version of the same app exists purely as a
  portfolio piece. **Share nothing with it**: separate database, storage,
  queue, API keys, domains, and Vercel project, so tearing it down can never
  affect real users' data.
