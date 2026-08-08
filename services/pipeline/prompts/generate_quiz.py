from pydantic import BaseModel, field_validator
import json


class QuizQuestionDraft(BaseModel):
    question: str
    choices: list[str]
    correct_option: str
    explanation: str



class QuizQutput(BaseModel):
    questions: list[QuizQuestionDraft]

    @field_validator("questions", mode="before")
    @classmethod
    def parse_if_string(cls, value):
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed.get("questions", parsed)
            return parsed
        return value



GENERATE_QUIZ_PROMPT = """You are creating multiple-choice quiz questions from a lecture note.

Summary of this part of the lecture:
{summary}

Key terms covered:
{key_terms}

Generate exactly {count} multiple-choice questions testing understanding of this material. Each question
should have exactly 4 choices. correct_option must be an exact copy of the correct choice's
text from the choices list — not a letter or index. Include a brief explanation of why the
correct answer is right. Avoid ambiguous questions or choices that are obviously wrong at a
glance — distractors should be plausible.
"""

