from langchain_anthropic import ChatAnthropic

from services.pipeline.prompts.generate_notes import GENERATE_NOTES_PROMPT, NoteOutput
from packages.shared_types.schemas import NoteBlock
from services.pipeline.state import LectureState


llm = ChatAnthropic(model_name="claude-sonnet-5", timeout=120)

def generate_notes(state: LectureState) -> LectureState:
    state.status = "generating_notes"

    structured_llm = llm.with_structured_output(NoteOutput)

    rolling_context = ""
    notes = []

    for segment in state.segments:
        result = structured_llm.invoke(
            GENERATE_NOTES_PROMPT.format(
                rolling_context=rolling_context,
                segment_text=segment.text
            )
        )

        notes.append(NoteBlock(
            segment_id=segment.id,
            summary=result.summary,
            key_terms=result.key_terms,
            rolling_context_used=rolling_context
        ))

        rolling_context = result.updated_rolling_summary

    state.notes = notes
    state.status = "done"
    return state

