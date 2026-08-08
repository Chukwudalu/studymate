import type { LectureState, LectureSummary } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// credentials: "include" sends/receives the httpOnly session cookie cross-site
// (Vercel -> API Gateway). The token itself is never visible to this JS at all.
function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_URL}${path}`, { ...init, credentials: "include" });
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export async function signup(email: string, password: string): Promise<void> {
  const res = await apiFetch("/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  await json(res);
}

export async function login(email: string, password: string): Promise<void> {
  const res = await apiFetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  await json(res);
}

export async function logout(): Promise<void> {
  await apiFetch("/auth/logout", { method: "POST" });
}

export async function checkAuth(): Promise<boolean> {
  const res = await apiFetch("/auth/me");
  return res.ok;
}

export async function presignUpload(): Promise<{ upload_url: string; audio_key: string }> {
  const res = await apiFetch("/uploads/presign", { method: "POST" });
  return json(res);
}

export async function uploadToS3(uploadUrl: string, file: File): Promise<void> {
  const res = await fetch(uploadUrl, { method: "PUT", body: file });
  if (!res.ok) {
    throw new Error(`S3 upload failed: ${res.status} ${res.statusText}`);
  }
}

export async function createLecture(audioKey: string, subject: string): Promise<{ lecture_id: string }> {
  const res = await apiFetch("/lectures", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_key: audioKey, subject }),
  });
  return json(res);
}

export async function getLecture(lectureId: string): Promise<LectureState> {
  const res = await apiFetch(`/lectures/${lectureId}`);
  return json(res);
}

export async function deleteLecture(lectureId: string): Promise<void> {
  const res = await apiFetch(`/lectures/${lectureId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
}

export async function listSubjects(): Promise<string[]> {
  const res = await apiFetch("/subjects");
  return json(res);
}

export async function listLectures(subject?: string): Promise<LectureSummary[]> {
  const path = subject ? `/lectures?subject=${encodeURIComponent(subject)}` : "/lectures";
  const res = await apiFetch(path);
  return json(res);
}

export async function generateFlashcards(lectureId: string, count: number): Promise<void> {
  const res = await apiFetch(`/lectures/${lectureId}/flashcards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count }),
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
}

export async function generateQuiz(lectureId: string, count: number): Promise<void> {
  const res = await apiFetch(`/lectures/${lectureId}/quiz`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count }),
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
}
