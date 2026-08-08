import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { presignUpload, uploadToS3, createLecture, listSubjects } from "./api";
import AudioRecorder from "./AudioRecorder";

export default function UploadPage() {
  const navigate = useNavigate();

  const [mode, setMode] = useState<"upload" | "record">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [subject, setSubject] = useState("");
  const [newSubject, setNewSubject] = useState("");
  const [isAddingSubject, setIsAddingSubject] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listSubjects().then(setSubjects).catch(() => {});
  }, []);

  const effectiveSubject = isAddingSubject ? newSubject.trim() : subject;
  const canUpload = file !== null && effectiveSubject.length > 0 && !uploading;

  function switchMode(next: "upload" | "record") {
    setMode(next);
    setFile(null);
    setError(null);
  }

  async function handleUpload() {
    if (!file || !effectiveSubject) return;
    setUploading(true);
    setError(null);
    try {
      const { upload_url, audio_key } = await presignUpload();
      await uploadToS3(upload_url, file);
      const { lecture_id } = await createLecture(audio_key, effectiveSubject);
      navigate(`/lecture/${lecture_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
    }
  }

  return (
    <div className="wrap">
      <section className="card">
        <div>
          <h1 className="display">Turn a lecture into something you can study</h1>
          <p className="lede">
            Record straight from your browser during class, or upload a file — either way
            we'll transcribe it, split it by topic, and write notes.
          </p>
        </div>

        <div className="mode-toggle">
          <button
            className={"btn " + (mode === "upload" ? "btn-primary" : "btn-ghost")}
            onClick={() => switchMode("upload")}
            type="button"
          >
            Upload a file
          </button>
          <button
            className={"btn " + (mode === "record" ? "btn-primary" : "btn-ghost")}
            onClick={() => switchMode("record")}
            type="button"
          >
            Record now
          </button>
        </div>

        {mode === "upload" ? (
          <input
            type="file"
            accept="audio/*"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        ) : (
          <AudioRecorder onRecordingComplete={setFile} />
        )}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
          {!isAddingSubject ? (
            <label>
              Subject
              <select value={subject} onChange={(e) => setSubject(e.target.value)}>
                <option value="">Select a subject…</option>
                {subjects.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              New subject
              <input
                type="text"
                value={newSubject}
                onChange={(e) => setNewSubject(e.target.value)}
                placeholder="e.g. Biology 201"
              />
            </label>
          )}
          <button
            className="btn btn-ghost"
            onClick={() => setIsAddingSubject((v) => !v)}
            type="button"
          >
            {isAddingSubject ? "Choose existing" : "Add new subject"}
          </button>
        </div>

        <button className="btn btn-primary" onClick={handleUpload} disabled={!canUpload}>
          {uploading ? "Uploading…" : "Upload & transcribe"}
        </button>

        {error && <div className="error-box">{error}</div>}
      </section>
    </div>
  );
}
