import { useState } from "react";
import type { QuizQuestion } from "./types";

export default function QuizView({ quiz }: { quiz: QuizQuestion[] }) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  if (quiz.length === 0) return null;
  const q = quiz[index];

  function choose(option: string) {
    if (selected !== null) return;
    setSelected(option);
  }

  function next() {
    setSelected(null);
    setIndex((i) => Math.min(quiz.length - 1, i + 1));
  }

  function prev() {
    setSelected(null);
    setIndex((i) => Math.max(0, i - 1));
  }

  return (
    <div className="quiz-section" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span className="section-label">Quiz</span>
        <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>
          {index + 1} / {quiz.length}
        </span>
      </div>

      <p className="quiz-q">{q.question}</p>

      <div className="quiz-options">
        {q.choices.map((choice, i) => {
          let className = "quiz-opt";
          if (selected !== null) {
            if (choice === q.correct_option) className += " correct";
            else if (choice === selected) className += " wrong";
          }
          return (
            <button key={choice} className={className} onClick={() => choose(choice)}>
              <span className="letter">{String.fromCharCode(65 + i)}</span>
              {choice}
            </button>
          );
        })}
      </div>

      {selected !== null && <p className="quiz-explain">{q.explanation}</p>}

      <div className="actions">
        <button className="btn btn-ghost" onClick={prev} disabled={index === 0}>
          ← Previous
        </button>
        <button className="btn btn-ghost" onClick={next} disabled={index === quiz.length - 1}>
          Next →
        </button>
      </div>
    </div>
  );
}
