from langgraph.graph import END, START, StateGraph

from agentlab.graph.nodes import Nodes
from agentlab.graph.state import AgentState


def build_graph(nodes: Nodes):
    graph = StateGraph(AgentState)
    graph.add_node("normalize", nodes.normalize)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("respond", nodes.respond)
    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "retrieve")
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", END)
    return graph.compile()
