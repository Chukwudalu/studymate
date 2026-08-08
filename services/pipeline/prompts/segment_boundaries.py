from pydantic import BaseModel


class TopicBoundaries(BaseModel):
    boundary_chunk_indices: list[int]



SEGMENT_BOUNDARIES_PROMPT = """
You are given a numbered list of transcript chunks from a lecture.
Identify which chunk indices mark the START of a new topic (a meaningful shift in subject matter).
Always include index 0.
Return only the chunk indices where a new topic begins — not every chunk.

Transcript chunks:
{numbered_chunks}
"""
