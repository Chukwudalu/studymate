import { useState } from "react";
import type { Flashcard } from "./types";

export default function FlashcardView({ flashcards }: { flashcards: Flashcard[] }) {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);

  if (flashcards.length === 0) return null;
  const card = flashcards[index];

  function go(delta: number) {
    setFlipped(false);
    setIndex((i) => Math.max(0, Math.min(flashcards.length - 1, i + delta)));
  }

  return (
    <div className="flash-section" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="section-label">Flashcards</span>
        <span className="flash-count" style={{ fontSize: 12, color: "var(--ink-faint)" }}>
          {index + 1} / {flashcards.length} · tap card to flip
        </span>
      </div>

      <div className="flashcard-scene" onClick={() => setFlipped((f) => !f)}>
        <div className={`flashcard${flipped ? " is-flipped" : ""}`}>
          <div className="flash-face flash-front">
            <span className="kicker">Front</span>
            <p className="body">{card.front}</p>
            {card.difficulty && <span className="diff-tag">{card.difficulty}</span>}
          </div>
          <div className="flash-face flash-back">
            <span className="kicker">Back</span>
            <p className="body">{card.back}</p>
          </div>
        </div>
      </div>

      <div className="actions">
        <button className="btn btn-ghost" onClick={() => go(-1)} disabled={index === 0}>
          ← Previous
        </button>
        <button className="btn btn-ghost" onClick={() => go(1)} disabled={index === flashcards.length - 1}>
          Next →
        </button>
      </div>
    </div>
  );
}
