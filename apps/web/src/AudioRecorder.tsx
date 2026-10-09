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
  const [level, setLevel] = useState(0);
  const [noSound, setNoSound] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const meterStopRef = useRef<(() => void) | null>(null);
  const peakRef = useRef(0);

  // Watches the live mic level so a dead/muted input is obvious while recording
  // instead of after the fact. Only reads the stream; it doesn't affect what is recorded.
  function startMeter(stream: MediaStream) {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    void ctx.resume();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const label = stream.getAudioTracks()[0]?.label || "your microphone";
    const startedAt = performance.now();
    peakRef.current = 0;
    let raf = 0;

    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const v of data) peak = Math.max(peak, Math.abs(v - 128) / 128);
      peakRef.current = Math.max(peakRef.current, peak);
      setLevel(Math.min(1, peak * 3));
      if (performance.now() - startedAt > 3000 && peakRef.current < 0.01) {
        setNoSound(`No sound is coming from "${label}". Check the microphone is not muted and that your browser and system allow microphone access.`);
      } else if (peakRef.current >= 0.01) {
        setNoSound(null);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    meterStopRef.current = () => {
      cancelAnimationFrame(raf);
      void ctx.close();
      setLevel(0);
    };
  }

  async function startRecording() {
    setError(null);
    setNoSound(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      startMeter(stream);

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        meterStopRef.current?.();
        meterStopRef.current = null;
        stream.getTracks().forEach((t) => t.stop());
        setNoSound(null);

        // An all-silent recording would just burn transcription calls, so don't keep it.
        if (peakRef.current < 0.003) {
          setError("That recording is silent - nothing was picked up from the microphone. Check it isn't muted, that your browser and system allow microphone access, or try another browser or input device.");
          return;
        }

        const type = recorder.mimeType;
        const extension = type.includes("webm") ? "webm" : type.includes("mp4") ? "m4a" : "ogg";
        const blob = new Blob(chunksRef.current, { type });
        const file = new File([blob], `recording.${extension}`, { type });
        setPreviewUrl(URL.createObjectURL(blob));
        onRecordingComplete(file);
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
          <div className="rec-meter" aria-hidden="true">
            <div className="rec-meter-fill" style={{ width: `${Math.round(level * 100)}%` }} />
          </div>
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

      {isRecording && noSound && <div className="rec-warning">{noSound}</div>}
      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
