from langgraph.graph import StateGraph, END
from packages.shared_types.schemas import LectureState
from services.pipeline.nodes.generate_quiz import generate_quiz


graph = StateGraph(LectureState)

graph.add_node("generate_quiz", generate_quiz)
graph.set_entry_point("generate_quiz")

graph.add_edge("generate_quiz", END)

quiz_graph = graph.compile()