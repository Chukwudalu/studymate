import { useState, type FormEvent } from "react";
import { sendChatMessage } from "./api";
import type { ChatMessage } from "./types";

export default function ChatPanel({ lectureId, initialMessages }: { lectureId: string; initialMessages: ChatMessage[] }) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = input.trim();
    if (!question || sending) return;

    setSending(true);
    setError(null);
    setInput("");

    try {
      const res = await sendChatMessage(lectureId, question);
      setMessages(res.chat_messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setInput(question);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-panel">
      <span className="section-label">Ask about this lecture</span>

      <div className="chat-messages">
        {messages.length === 0 && <p className="lede">Ask a question about the notes above.</p>}
        {messages.map((message, i) => (
          <div key={i} className={`chat-bubble chat-bubble-${message.role}`}>
            {message.content}
          </div>
        ))}
        {sending && <div className="chat-bubble chat-bubble-assistant chat-bubble-pending">Thinking…</div>}
      </div>

      <form onSubmit={handleSubmit} className="chat-input-row">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this lecture…"
          disabled={sending}
        />
        <button className="btn btn-primary" type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>

      {error && <div className="error-box">{error}</div>}
    </div>
  );
}
