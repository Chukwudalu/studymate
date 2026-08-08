from pydantic import BaseModel

class NoteOutput(BaseModel):
   summary: str
   key_terms: list[str]
   updated_rolling_summary: str



GENERATE_NOTES_PROMPT = """
You are summarizing a lecture, one topic segment at a time.

Here is what has been covered so far in the lecture (empty if this is the first segment):
{rolling_context}

Here is the next segment's raw transcript text:
{segment_text}

Do three things:
1. Write a concise summary of THIS segment only. Use the prior context above to correctly
   resolve any references to earlier material (e.g. "as I mentioned earlier", "going back to X").
2. List the key terms/concepts introduced or discussed in this segment, as short standalone phrases.
3. Write an updated rolling summary covering the ENTIRE lecture so far (prior context + this
   segment), to be passed forward as context when processing the next segment.
"""