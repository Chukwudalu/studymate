from langgraph.graph import StateGraph, END

from services.pipeline.nodes.generate_flashcards import generate_flashcards
from services.pipeline.state import LectureState

graph = StateGraph(LectureState)

graph.add_node("generate_flashcards", generate_flashcards)

graph.set_entry_point("generate_flashcards")
graph.add_edge("generate_flashcards", END)

flashcards_graph = graph.compile()