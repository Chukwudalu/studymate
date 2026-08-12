from langchain_anthropic import ChatAnthropic

from packages.shared_types.schemas import ChatMessage, NoteBlock

llm = ChatAnthropic(model_name="claude-sonnet-5", timeout=25)

CHAT_PROMPT = """You are a helpful study assistant answering a student's question about their lecture notes.

Only answer using the notes below. If the answer isn't covered in the notes, say so plainly instead of guessing.

Lecture notes:
{notes_context}
{history_block}
Student's question:
{question}
"""


def _notes_context(notes: list[NoteBlock]) -> str:
    return "\n\n".join(f"- {n.summary}\n  Key terms: {', '.join(n.key_terms)}" for n in notes)


def _history_block(history: list[ChatMessage]) -> str:
    if not history:
        return ""
    lines = "\n".join(f"{m.role}: {m.content}" for m in history)
    return f"\nConversation so far:\n{lines}\n"


def answer_question(notes: list[NoteBlock], history: list[ChatMessage], question: str) -> str:
    prompt = CHAT_PROMPT.format(
        notes_context=_notes_context(notes),
        history_block=_history_block(history),
        question=question,
    )
    result = llm.invoke(prompt)

    # With extended thinking, .content is a list of blocks (thinking/signature + text)
    # rather than a plain string - only the text blocks are the actual answer.
    if isinstance(result.content, str):
        return result.content
    return "".join(block["text"] for block in result.content if block.get("type") == "text")
