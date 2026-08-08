import uuid

from langchain_anthropic import ChatAnthropic
from services.pipeline.prompts.generate_quiz import GENERATE_QUIZ_PROMPT, QuizQutput
from packages.shared_types.schemas import QuizQuestion
from services.pipeline.state import LectureState


llm = ChatAnthropic(model_name="claude-sonnet-5", timeout=120)


def distribute_count(total: int, num_parts: int) -> list[int]:
    if num_parts == 0:
        return []
    base = total // num_parts
    remainder = total % num_parts
    return [base + 1 if i < remainder else base for i in range(num_parts)]


def generate_quiz(state: LectureState) -> LectureState:
    state.quiz_status = "generating"

    structured_llm = llm.with_structured_output(QuizQutput)
    counts = distribute_count(state.quiz_count, len(state.notes))
    quiz = []

    for note, count in zip(state.notes, counts):
        if count == 0:
            continue

        result = structured_llm.invoke(
            GENERATE_QUIZ_PROMPT.format(
                summary=note.summary,
                key_terms=", ".join(note.key_terms),
                count=count,
            )
        )

        for draft in result.questions:
            quiz.append(QuizQuestion(
                id=str(uuid.uuid4()),
                question=draft.question,
                choices=draft.choices,
                correct_option=draft.correct_option,
                explanation=draft.explanation,
                source_segment_id=note.segment_id
            ))

    state.quiz = quiz
    state.quiz_status = "done"
    return state