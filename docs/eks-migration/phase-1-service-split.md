# Phase 1 — Splitting the Monolith into `auth-service` and `core-api`

## What this phase was for

Phase 0 built somewhere for services to run. Phase 1 built the first two of
those services, by splitting the single `apps/api` FastAPI app (which
currently backs the live Lambda) into two independent codebases:
`auth-service` (signup/login/reset/logout/me) and `core-api` (lecture CRUD,
presign, chat, enqueueing). The `worker` stayed code-wise almost untouched —
only its one import of lecture-DB functions moved to point at the new
`core-api` package instead of the old `apps.api`.

Critically: **the old `apps/api` directory was never touched.** It still
exists, unmodified, still backing the live Lambda in production. Everything
in this phase is new, parallel code that doesn't affect the running system
until we deliberately cut over in a later phase.

---

## Part 1 — Concepts, explained from zero

### Why split a working monolith at all?

The single `apps/api/main.py` mixed two genuinely different concerns:
*identity* (who is this person, is their session valid) and *lecture
business logic* (CRUD, file uploads, AI chat). They happened to live in one
FastAPI app because that was the simplest thing to build first — but they
have different scaling needs, different AWS permissions, and different
failure blast radii. Splitting them is what "microservices" concretely
means here: not a buzzword, just "these two things can now fail, deploy,
and scale independently of each other."

### The real design question: what do the two services *share*?

This is the part worth understanding, not just the file layout. Both new
services need to verify a user's session cookie — but only `auth-service`
should know how to *create* one (password hashing, issuing a token).
Giving `core-api` that code too would mean two copies of security-sensitive
logic that can silently drift apart. The fix: extract just the read-only
half — "given a token, who is this user" — into a small shared package
(`packages/shared_auth/jwt.py`) that both services import, while
password/signup/cookie-issuing logic (`apps/auth_service/auth.py`) stays
exclusively in `auth-service`. This is a common, correct pattern:
**services can share a library of pure, stateless logic; they should not
share a service's authority to make decisions.** `core-api` can *verify* a
session; only `auth-service` can *create* one.

### Why the database didn't need to change

Both new services still connect to the exact same Supabase Postgres
database via the exact same `DATABASE_URL` — `auth-service` only touches
the `users` table, `core-api` only touches `lectures`. This mirrors how
the monolith already worked internally (different Python modules, same
database). The "textbook" microservices answer is *database-per-service* —
each service owns its schema exclusively, and nothing else queries it
directly — but that's real migration work (schema ownership, no more
cross-service joins) that teaches nothing new about Docker/Kubernetes/
Terraform, which is the actual point of this project. Deliberately skipped
for now; a good follow-up exercise later, on its own.

---

## Part 2 — What we actually built, file by file

### `packages/shared_auth/jwt.py` (new)
The one genuinely new piece of logic, not just a copy-paste. Holds
`get_current_user_id(request)` — pure JWT verification (decode the cookie,
check signature/expiry, return the user id). No password hashing, no
cookie-writing. Both `auth-service` and `core-api` depend on this for their
`Depends(get_current_user_id)` route guards.

### `apps/auth_service/` (new)
- `db.py` — bare `get_connection()` helper (own copy, not shared — see
  below for why)
- `users_db.py` — user CRUD against Postgres, moved verbatim from
  `apps/api/users_db.py`
- `auth.py` — password hashing, JWT *issuing*, cookie set/clear. Imports
  the shared `AUTH_JWT_SECRET`/`COOKIE_NAME` constants from
  `packages/shared_auth/jwt.py` so both services agree on cookie naming
  without duplicating the secret-loading logic
- `main.py` — FastAPI app exposing only `/auth/*` routes, plus `/healthz`
- `requirements.txt` — notably: no `boto3`, no `mangum`, no
  `langchain-anthropic` — this service never touches S3, SQS, or an LLM

### `apps/core_api/` (new)
- `db.py` — lecture CRUD against Postgres, moved verbatim from
  `apps/api/db.py`
- `chat.py`, `queue.py` — moved verbatim
- `main.py` — FastAPI app exposing everything except `/auth/*`: lecture
  CRUD, `/uploads/presign`, `/lectures/{id}/chat`, plus `/healthz`. Imports
  `get_current_user_id` from `packages.shared_auth.jwt` for its own route
  guards
- `requirements.txt` — has `boto3` (S3 presigning) and
  `langchain-anthropic` (chat), which `auth-service` deliberately doesn't

### `apps/worker/jobs.py` (existing file, one-line change)
`from apps.api.db import ...` → `from apps.core_api.db import ...`. This is
the only change to existing application code in this entire phase — the
worker's job-dispatch logic itself is untouched, it just now reads/writes
lecture state through the new `core_api` package instead of the old `api`
one.

### Why `apps/auth_service/db.py` duplicates `get_connection()` instead of importing it from `core_api`
Small, deliberate choice: if `auth-service` imported `apps.core_api.db`
just to get a database connection helper, it would create a real
dependency between two services that are supposed to be independently
deployable — a change to `core_api`'s file layout could break
`auth-service`'s build. Four lines of duplicated `psycopg.connect(...)`
code is cheaper than that coupling.

### Dockerfiles
- `Dockerfile.auth-service` / `Dockerfile.core-api` (new) — both
  `python:3.13-slim`, `pip install` their own `requirements.txt`, `COPY`
  only their own app directory plus the two `packages/` they need, and run
  via plain `uvicorn` on port 8000. No Lambda-specific base image, no
  Mangum handler — these are ordinary HTTP servers now.
- `Dockerfile.worker` — one-line change: `COPY apps/api apps/api` →
  `COPY apps/core_api apps/core_api`, matching the `jobs.py` import change.
- `Dockerfile.api` — **untouched**. Still builds the Lambda-shaped image
  from the old `apps/api`, still what the live Lambda runs.

### `/healthz` on both new services
A bare route with no auth dependency, added specifically for Kubernetes
liveness/readiness probes in a later phase. `/auth/me` requires a valid
cookie and would always read as "unhealthy" to a probe that doesn't have
one — a dedicated health route is the standard fix.

### `docker-compose.yml` (extended)
Added `auth-service`, `core-api`, and `worker` as buildable, runnable
services alongside the pre-existing (unused) `postgres`/`redis` entries.
Each mounts `~/.aws:/root/.aws:ro` read-only so the containers can use
your host's real AWS credentials — deliberately **not** faking S3/SQS
locally. The whole point of this phase's testing was proving the split
works against real infrastructure, not a mock.

---

## Part 3 — Bugs and surprises, and what each one teaches

### Bug 1 — Lambda image missing, again
Same root cause as Phase 0's Bug 4: the environment had been torn down and
rebuilt overnight, and `force_delete = true` on the ECR repos means every
fresh `apply` needs images pushed before Lambda/ECS resources that
reference `:latest` can succeed. Not new territory, just a repeat — worth
noting because it's now a recognized *pattern*, not a one-off surprise:
**whenever this environment gets torn down, images need re-pushing before
the next apply, every time, no exceptions.**

### Bug 2 — "Internal Server Error" on signup: an external dependency, not a code bug
The very first end-to-end test failed with a bare 500 on `/auth/signup`.
The traceback pointed at `psycopg.OperationalError: ... tenant/user
postgres.gtvfilouerqevsbrwdol not found` — Supabase's connection pooler
rejecting the connection outright, not a timeout. Reproduced identically
**both from inside the Docker container and directly from the host**,
which is what confirmed this wasn't a networking or code issue at all: a
paused Supabase project (common on the free tier after a week of
inactivity). The fix was outside this codebase entirely — resuming the
project from the Supabase dashboard.
**Lesson:** when a new failure shows up, reproduce it from the *simplest*
possible environment before debugging the complex one. Testing the exact
same connection from a bare Python `venv` on the host, no Docker involved,
took two minutes and immediately proved the container/network stack was
innocent — saving a lot of wasted debugging inside Docker.

### Bug 3 — worker crashed permanently on a transient SQS timing issue
After Supabase came back and the whole AWS stack was rebuilt via
`terraform apply`, the worker container (which had been started slightly
*before* Terraform finished recreating the SQS queue) hit
`QueueDoesNotExist` on its very first `receive_message` call. Because
`apps/worker/run.py`'s main polling loop has no `try/except` around the
`receive_message` call itself (only around the job-handling code inside
the loop), that one exception crashed the entire process — and since
`docker-compose.yml` has no restart policy, the container just sat dead
for the next two hours while unrelated Terraform work continued.
**How this was actually diagnosed, step by step** (worth studying the
process, not just the answer):
1. `docker compose logs worker` showed the crash — but that log line's
   timestamp turned out to be from hours earlier, not "now." Easy to
   misread as an active, ongoing failure.
2. `aws sqs get-queue-url` from the host confirmed the queue *did* exist
   right now.
3. `docker inspect`'s `StartedAt` / `RestartCount` fields revealed the
   container had been quietly restarted and was running cleanly with zero
   crashes since — the alarming log line was stale history, not a live
   symptom.
4. A direct `receive_message` call run manually inside the container
   (`docker compose exec worker python3 -c "..."`) succeeded immediately,
   proving the *current* state was healthy.
**Lesson:** `docker compose logs` (and similarly, `kubectl logs`) shows
*cumulative* history across restarts by default, not just "what's
happening right now." Before treating an error line as an active problem,
check *when* it happened (`docker inspect`'s timestamps, or `logs -t`) —
otherwise you can spend real time debugging a problem that already
resolved itself.
**The underlying fix, not yet applied:** `run.py`'s `receive_message` call
should genuinely be wrapped in a retry/backoff, the same way the
job-handling code inside the loop already is — a transient AWS API hiccup
shouldn't be able to kill the whole worker process. Worth fixing before
this goes anywhere near production; noted here rather than silently
patched, since it's pre-existing behavior from the original monolith, not
something this migration introduced.

---

## Part 4 — How we proved it actually works

Applying/building without errors isn't proof — Phase 0 already taught that
lesson, and it held here too. The real verification was one continuous,
real request flow against real infrastructure:

1. **Signup** against `auth-service` (`POST :8001/auth/signup`) → got a
   session cookie back.
2. **`GET :8001/auth/me`** with that cookie → confirmed `auth-service`
   itself accepts its own cookie.
3. **`GET :8000/subjects`** (on `core-api`, a completely different
   process, different container) with the *same* cookie → succeeded. This
   is the one result that actually proves the split works: two
   independent services, sharing nothing but a JWT secret and a verification
   function, correctly agreeing on who's making the request.
4. **`POST :8000/uploads/presign`** → got back a real, validly-signed S3
   URL.
5. **`POST :8000/lectures`** → created a lecture row in Postgres and
   enqueued a real SQS message.
6. Watched the **`worker`** (separate container, separate codebase) pick
   that message up (`ApproximateNumberOfMessages` 1 → 0), attempt real
   transcription, hit a real (expected) S3 403 since no actual audio was
   uploaded, and correctly write `status: "failed"` with the real error
   message back to Postgres.
7. **`GET :8000/lectures/{id}`** on `core-api` read that same failure state
   back out correctly.

That's every seam in the new architecture exercised by one real flow:
cross-service auth, S3, SQS, and Postgres, all through the actual AWS
resources Phase 0 and the pre-existing infra provide — no mocking.

---

## What exists now, concretely

```bash
cd /home/jeremiah/coding/studymate
docker compose up -d auth-service core-api worker
curl http://localhost:8001/healthz   # auth-service
curl http://localhost:8000/healthz   # core-api
docker compose logs worker           # SQS poll loop, silent unless there's a job or error
```

Still not done: no Kubernetes deployment of these two services yet (that's
Phase 2, via Helm), and the old Lambda/ECS setup is still what's actually
live in production — nothing has cut over yet.
