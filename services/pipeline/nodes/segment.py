from langchain_anthropic import ChatAnthropic

from services.pipeline.prompts.segment_boundaries import SEGMENT_BOUNDARIES_PROMPT, TopicBoundaries
from packages.shared_types.schemas import Segment
from services.pipeline.state import LectureState


llm = ChatAnthropic(model_name="claude-sonnet-5", timeout=120)

def segment(state: LectureState) -> LectureState:
    state.status = "segmenting"

    numbered_chunks = "\n".join(
        f"[{i}] {chunk.text}" for i, chunk in enumerate(state.raw_chunks)
    )

    structured_llm = llm.with_structured_output(TopicBoundaries)

    result = structured_llm.invoke(
        SEGMENT_BOUNDARIES_PROMPT.format(numbered_chunks=numbered_chunks)
    )

    boundaries = sorted(set(result.boundary_chunk_indices) | {0}) 
    boundaries.append(len(state.raw_chunks))

    segments = []
    for i in range(len(boundaries) - 1):
        start_idx, end_idx = boundaries[i], boundaries[i+1]
        chunk_group = state.raw_chunks[start_idx:end_idx]

        segments.append(Segment(
            id=f"seg_{i}",
            start_ms=chunk_group[0].start_ms,
            end_ms=chunk_group[-1].end_ms,
            text=" ".join(c.text for c in chunk_group),
        ))
    state.segments = segments
    return state

        

