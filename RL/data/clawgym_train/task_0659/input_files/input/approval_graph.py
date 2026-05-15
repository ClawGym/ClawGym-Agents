"""
Approval workflow graph (Python) — intentionally includes issues for code review.

This file models an approval process using a LangGraph-style StateGraph with several
mistakes to be surfaced in review:
- State mutation instead of return
- Missing reducers for list fields
- Wrong return from conditional edge
- Interrupt without checkpointer
- Missing thread_id with checkpointer
- Async issues (blocking call)
- Tool integration gaps (tool_calls without ToolMessage)
- Graph structure issues (unreachable node, missing conditional paths)
- Command destinations omitted
- Performance issues (large state stored every step)
"""

from typing import TypedDict, Annotated, Literal, Dict, Any
import operator
import asyncio

# Simulated imports for illustration purposes
from langgraph.graph import StateGraph, START, END, Command
from langgraph.checkpoint.memory import InMemorySaver
# NOTE: interrupt usage assumes a prebuilt interrupt mechanism exists
# In actual code, import the correct interrupt for your stack.
from langgraph.prebuilt import interrupt  # Placeholder for demonstration

# LangChain-like messages for tool integration example
from langchain_core.messages import HumanMessage, AIMessage  # ToolMessage intentionally omitted
# requests used incorrectly in async context below
import requests


class ApprovalState(TypedDict, total=False):
    # ISSUE: Missing reducer for list fields — each update may overwrite rather than append
    messages: list  # should be Annotated[list, add_messages] in real code
    approvals: int
    approved_by: list  # should have a reducer/merge strategy
    risk_score: float
    large_log_blob: str  # performance concern if populated on each step


# CRITICAL ISSUE: Mutates state in place
def start(state: ApprovalState) -> None:
    # BAD: Direct mutation of state messages (should return partial update)
    state.setdefault("messages", [])
    state["messages"].append(("system", "Starting approval workflow"))


# STATE SCHEMA ISSUE: Returns full state instead of partial updates
def collect_manager_approval(state: ApprovalState) -> ApprovalState:
    approvals = state.get("approvals", 0) + 1
    approved_by = (state.get("approved_by") or []) + ["manager@example.com"]
    # BAD: returns entire state, potentially resetting concurrent fields
    return {
        "messages": state.get("messages", []) + [("assistant", "Manager approved")],
        "approvals": approvals,
        "approved_by": approved_by,
        "risk_score": state.get("risk_score", 0.2),
        "large_log_blob": "x" * 10_000_000,  # PERFORMANCE ISSUE: huge data persisted every step
    }


# GRAPH STRUCTURE + CONDITIONAL EDGE ISSUE:
# - Literal includes 'compliance_review' but router sometimes returns an unknown node
def router(state: ApprovalState) -> Literal["security_review", "compliance_review", "__end__"]:
    if state.get("risk_score", 0) > 0.5:
        return "security_review"
    if state.get("approvals", 0) >= 2:
        # BAD: returning a non-existent node will cause runtime error
        return "nonexistent_node"  # WRONG RETURN TYPE / INVALID DESTINATION
    return "__end__"


# ASYNC ISSUE: blocking HTTP call used in async function
async def security_review(state: ApprovalState) -> Dict[str, Any]:
    # BAD: Blocking I/O inside async — should use an async HTTP client
    r = requests.get("https://example.org/security-check", timeout=1)
    verdict = "ok" if r.status_code == 200 else "investigate"
    return {"messages": [("assistant", f"Security review: {verdict}")],
            "approvals": state.get("approvals", 0) + (1 if verdict == "ok" else 0)}


# CHECKPOINTING ISSUE: interrupt used without checkpointer in compiled graph
def interrupt_for_human(state: ApprovalState) -> Dict[str, Any]:
    user_ack = interrupt("Please confirm go/no-go for deployment")  # requires checkpointer
    return {"messages": [("human", f"Manager says: {user_ack}")]}


# TOOL INTEGRATION ISSUE: tool_calls present without ToolMessage follow-up
def tool_calling_node(state: ApprovalState) -> Dict[str, Any]:
    msgs = state.get("messages", [])
    msgs.extend([
        HumanMessage(content="Check change ticket FW-2026-0419-OPS"),
        AIMessage(content="", tool_calls=[{"id": "1", "name": "ticket_lookup", "args": {"id": "FW-2026-0419-OPS"}}]),
        # BAD: Missing ToolMessage for tool_call_id "1"
    ])
    return {"messages": msgs}


# GRAPH STRUCTURE / VIZ ISSUE: Command without declared destinations
def dynamic_command(state: ApprovalState) -> Command[Literal["next", "__end__"]]:
    if state.get("approvals", 0) >= 2:
        return Command(goto="__end__")
    return Command(goto="next")


# UNREACHABLE NODE (orphan)
def orphan(state: ApprovalState) -> Dict[str, Any]:
    return {"messages": [("assistant", "I am never reached")]}


def build_graph() -> Any:
    builder = StateGraph(ApprovalState)

    builder.add_node("start", start)
    builder.add_node("collect_manager_approval", collect_manager_approval)
    builder.add_node("security_review", security_review)
    builder.add_node("interrupt_for_human", interrupt_for_human)
    builder.add_node("tool_calling_node", tool_calling_node)
    # BAD: destinations omitted for dynamic node (affects visualization and analysis)
    builder.add_node("dynamic_command", dynamic_command)
    builder.add_node("orphan", orphan)  # Unreachable on purpose

    # Entry path
    builder.add_edge(START, "start")
    builder.add_edge("start", "collect_manager_approval")

    # Conditional edges — MISSING mapping for "compliance_review"
    builder.add_conditional_edges(
        "collect_manager_approval",
        router,
        {
            "security_review": "security_review",
            "__end__": END,
            # "compliance_review" missing on purpose
        },
    )

    # Linear path
    builder.add_edge("security_review", "interrupt_for_human")
    builder.add_edge("interrupt_for_human", END)

    # Compile WITHOUT checkpointer — interrupts will not work (issue)
    graph = builder.compile()
    return graph


def example_invocations():
    graph = build_graph()

    # CHECKPOINTING ISSUE: invoking graph with interrupt but no checkpointer will fail at runtime
    result = graph.invoke(
        {"messages": [("human", "kickoff")], "approvals": 0, "approved_by": [], "risk_score": 0.7}
    )
    print(result)

    # Compile with in-memory checkpointer for demonstration
    builder2 = StateGraph(ApprovalState)
    builder2.add_node("start", start)
    builder2.add_edge(START, "start")
    graph2 = builder2.compile(checkpointer=InMemorySaver())

    # THREAD ID ISSUE: Using a checkpointer requires a thread_id in config; omitted here
    result2 = graph2.invoke({"messages": [("human", "hello")]})
    print(result2)

    # SUBGRAPH CHECKPOINTER CONFUSION: explicit False prevents inheritance
    sub_builder = StateGraph(ApprovalState)
    sub_builder.add_node("tool_calling_node", tool_calling_node)
    sub_graph = sub_builder.compile(checkpointer=False)  # should be None to inherit

    # PARALLEL TOOL CALLS BEFORE INTERRUPT (conceptual example)
    # (Pseudo-code to illustrate configuration mistake; not executed here)
    from langchain.chat_models import ChatOpenAI  # type: ignore
    interrupt_tool = object()  # placeholder
    other_tool = object()      # placeholder
    model = ChatOpenAI().bind_tools([interrupt_tool, other_tool], parallel_tool_calls=True)
    _ = model  # suppress unused warning


if __name__ == "__main__":
    example_invocations()