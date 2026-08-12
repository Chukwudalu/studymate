export interface RawChunk {
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface Segment {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  topic_label: string | null;
}

export interface NoteBlock {
  segment_id: string;
  summary: string;
  key_terms: string[];
  rolling_context_used: string | null;
}

export interface Flashcard {
  id: string;
  front: string;
  back: string;
  source_segment_id: string;
  difficulty: "easy" | "medium" | "hard" | null;
}

export interface QuizQuestion {
  id: string;
  question: string;
  choices: string[];
  correct_option: string;
  explanation: string;
  source_segment_id: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export type LectureStatus =
  | "queued"
  | "transcribing"
  | "segmenting"
  | "generating_notes"
  | "done"
  | "failed";

export type ArtifactStatus = "not requested" | "queued" | "generating" | "done" | "failed";

export interface LectureState {
  lecture_id: string;
  user_id: string;
  subject: string;
  status: LectureStatus;
  flashcards_status: ArtifactStatus;
  quiz_status: ArtifactStatus;
  raw_transcript: string | null;
  raw_chunks: RawChunk[];
  audio_key: string;
  flashcards_count: number;
  quiz_count: number;
  segments: Segment[];
  notes: NoteBlock[];
  flashcards: Flashcard[];
  quiz: QuizQuestion[];
  chat_messages: ChatMessage[];
  transcription_errors: string[];
  flashcards_errors: string[];
  quiz_errors: string[];
}

export interface LectureSummary {
  lecture_id: string;
  user_id: string;
  subject: string;
  status: string;
  created_at: string;
}
