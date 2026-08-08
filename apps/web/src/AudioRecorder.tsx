import { useRef, useState } from "react";

interface Props {
  onRecordingComplete: (file: File) => void;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function AudioRecorder({ onRecordingComplete }: Props) {
  const [isRecording, setIsRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        const extension = recorder.mimeType.includes("webm") ? "webm" : "ogg";
        const file = new File([blob], `recording.${extension}`, { type: recorder.mimeType });
        setPreviewUrl(URL.createObjectURL(blob));
        onRecordingComplete(file);
        stream.getTracks().forEach((t) => t.stop());
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
      setElapsed(0);
      timerRef.current = window.setInterval(() => setElapsed((e) => e + 1), 1000);
    } catch {
      setError("Couldn't access your microphone. Check browser permissions and try again.");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function reRecord() {
    setPreviewUrl(null);
    setElapsed(0);
  }

  return (
    <div className="recorder">
      {!previewUrl && !isRecording && (
        <button className="btn btn-primary" onClick={startRecording} type="button">
          ● Start recording
        </button>
      )}

      {isRecording && (
        <div className="recorder-live">
          <span className="rec-dot" />
          <span className="rec-timer">{formatElapsed(elapsed)}</span>
          <button className="btn btn-danger" onClick={stopRecording} type="button">
            Stop
          </button>
        </div>
      )}

      {previewUrl && !isRecording && (
        <div className="recorder-preview">
          <audio src={previewUrl} controls />
          <button className="btn btn-ghost" onClick={reRecord} type="button">
            Re-record
          </button>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
