from typing import Literal
from pydantic import BaseModel, field_validator
import json



class FlashcardDraft(BaseModel):
    front: str
    back: str
    difficulty: Literal["easy", "medium", "hard"] | None = None


class FlashcardsOutput(BaseModel):
    flashcards: list[FlashcardDraft]

    @field_validator("flashcards", mode="before")
    @classmethod
    def parse_if_string(cls, value):
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get("flashcards", parsed)
            return parsed
        return value





GENERATE_FLASHCARDS_PROMPT = """You are creating study flashcards from a lecture note
summary of this part of the lecture:
{summary}

key terms covered:
{key_terms}

Generate exactly {count} flashcards testing understanding of this material. Each flashcard should have
a clear question/prompt on the front and a concise, accurate answer on the back. Avoid
trivial yes/no questions — favor questions that test real understanding of the concept.
"""