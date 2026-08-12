from apps.api import chat
from packages.shared_types.schemas import NoteBlock


class FakeResult:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, prompt):
        return FakeResult(self._content)


def test_answer_question_handles_plain_string_content(monkeypatch):
    monkeypatch.setattr(chat, "llm", FakeLLM("Mitosis has four phases."))

    answer = chat.answer_question(
        notes=[NoteBlock(segment_id="seg-1", summary="Mitosis has four phases.", key_terms=["mitosis"])],
        history=[],
        question="How many phases does mitosis have?",
    )

    assert answer == "Mitosis has four phases."


def test_answer_question_handles_content_block_list(monkeypatch):
    # Regression guard: with extended thinking, ChatAnthropic returns a list of
    # content blocks (thinking/signature + text) instead of a plain string.
    blocks = [
        {"type": "thinking", "thinking": "let me think...", "signature": "abc"},
        {"type": "text", "text": "Mitosis has four phases."},
    ]
    monkeypatch.setattr(chat, "llm", FakeLLM(blocks))

    answer = chat.answer_question(
        notes=[NoteBlock(segment_id="seg-1", summary="Mitosis has four phases.", key_terms=["mitosis"])],
        history=[],
        question="How many phases does mitosis have?",
    )

    assert answer == "Mitosis has four phases."
