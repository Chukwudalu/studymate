from langgraph.graph import StateGraph, END

from services.pipeline.nodes.transcribe import transcribe
from services.pipeline.nodes.segment import segment
from services.pipeline.nodes.generate_notes import generate_notes
from services.pipeline.state import LectureState


graph = StateGraph(LectureState)

graph.add_node("transcribe", transcribe)
graph.add_node("segment", segment)
graph.add_node("generate_notes", generate_notes)

graph.set_entry_point("transcribe")
graph.add_edge("transcribe", "segment")
graph.add_edge("segment", "generate_notes")
graph.add_edge("generate_notes", END)

transcription_graph = graph.compile()


