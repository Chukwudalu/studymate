import os
import tempfile
import boto3
from botocore.client import Config
from openai import OpenAI
from pydub import AudioSegment
from packages.shared_types.schemas import RawChunk
from services.pipeline.state import LectureState


client = OpenAI(timeout=300)
s3 = boto3.client(
    "s3",
    region_name="us-west-2",
    endpoint_url="https://s3.us-west-2.amazonaws.com",
    config=Config(signature_version="s3v4"),
)
S3_BUCKET = os.environ["S3_BUCKET"]
MAX_CHUNK_MS = 20*60*1000  # ~20 mins chunks, safely under whispers 25MB limit

def transcribe(state: LectureState) -> LectureState:
    state.status = "transcribing"

    local_path = download_audio(state.audio_key)
    audio = AudioSegment.from_file(local_path)

    raw_chunks = []
    offset_ms = 0
    for chunk_start in range(0, len(audio), MAX_CHUNK_MS):
        chunk_audio = audio[chunk_start:chunk_start+MAX_CHUNK_MS]
        chunk_path = f"{local_path}_{chunk_start}.mp3"
        chunk_audio.export(chunk_path, format="mp3")

        with open(chunk_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )

        for seg in result.segments:
            raw_chunks.append(RawChunk(
                text=seg.text,
                start_ms=offset_ms + int(seg.start * 1000),
                end_ms=offset_ms + int(seg.end * 1000),
            ))
        offset_ms += len(chunk_audio)
    state.raw_transcript = " ".join(c.text for c in raw_chunks)
    state.raw_chunks = raw_chunks
    return state


def download_audio(audio_key: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    s3.download_file(S3_BUCKET, audio_key, tmp.name)
    return tmp.name
