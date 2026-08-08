import uuid
from langchain_anthropic import ChatAnthropic
from services.pipeline.prompts.generate_flashcards import GENERATE_FLASHCARDS_PROMPT, FlashcardsOutput
from packages.shared_types.schemas import Flashcard
from services.pipeline.state import LectureState



llm = ChatAnthropic(model_name="claude-sonnet-5", timeout=120)


def distribute_count(total: int, num_parts: int) -> list[int]:
    if num_parts == 0:
        return []
    base = total // num_parts
    remainder = total % num_parts
    return [base + 1 if i < remainder else base for i in range(num_parts)]


def generate_flashcards(state: LectureState) -> LectureState:
    state.flashcards_status = "generating"

    structured_llm = llm.with_structured_output(FlashcardsOutput)
    counts = distribute_count(state.flashcards_count, len(state.notes))

    flashcards = []
    for note, count in zip(state.notes, counts):
        if count == 0:
            continue

        result = structured_llm.invoke(
            GENERATE_FLASHCARDS_PROMPT.format(
                summary=note.summary,
                key_terms=", ".join(note.key_terms),
                count=count,
            )
        )

        for draft in result.flashcards:
            flashcards.append(Flashcard(
                id=str(uuid.uuid4()),
                front=draft.front,
                back=draft.back,
                source_segment_id=note.segment_id,
                difficulty=draft.difficulty
            ))

    state.flashcards = flashcards
    state.flashcards_status = "done"
    return state




