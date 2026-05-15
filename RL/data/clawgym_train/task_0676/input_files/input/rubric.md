# Acceptance Rubric — Multi-Actor Docs Assistant

Scope: This rubric governs both code (agent_graph.py) and documentation (README.md, METACOGNITION.md), and the sample flows.

1) Architecture & State
- Typed Shared State present (TypedDict) with 'messages' using Annotated[..., add_messages] reducer to append chat history.
- Additional fields support planning, research, writing, editing (plan, research_requests, draft, edits, citations, query_type, requires_approval, counters, exit_status).

2) Nodes & Responsibilities (Multi-actor)
- Required nodes: Supervisor (router), Planner, Researcher (tool-calling preparer), Tools (dedicated ToolNode), Writer, Editor.
- Nodes must return partial state updates (dict) and not mutate global state in place.

3) Control Flow & Conditional Routing
- Graph created via StateGraph.
- Nodes added via add_node(), deterministic edges via add_edge(), and dynamic routing via add_conditional_edges().
- Supervisor implements routing logic with clear exit conditions (END on exit_status='done' or guards).
- Tools loop back to Supervisor; no infinite loops (bounded by loop guards).

4) Human-in-the-Loop Approval
- compile(..., interrupt_before=['tools']) configured so execution pauses prior to external tool actions.
- When requires_approval=false, run doesn’t pause.
- If approval is denied or skipped, pending_tool_call is cleared and flow proceeds without tool side effects.

5) Persistence / Checkpointing
- compile(..., checkpointer=...) enabled; MemorySaver acceptable.
- Demonstrate thread_id usage or equivalent to resume a run.

6) Streaming & Event Semantics
- Implementation supports both app.invoke(...) and app.stream(...).
- Streaming yields node-level events (start/end) and tool events where applicable.

7) Safety & Non-Functional
- All tools are stubbed and non-destructive (no real network/filesystem mutation).
- Guard against infinite loops (max_turns, max_tool_loops).
- Respect privacy and avoid embedding secrets in logs.

8) Documentation (README.md)
Must include clearly labeled sections (case-insensitive OK):
- State Schema & Reducers
- Nodes & Responsibilities
- Control Flow & Conditional Routing
- Human-in-the-Loop Approval
- Persistence/Checkpointing
- Streaming & Event Semantics
- How to Run
Also include references to Supervisor and Multi-actor design.

9) Metacognitive Protocol (METACOGNITION.md)
- Must explicitly cover:
  - Intent Decoding
  - Difficulty Assessment
  - Boundary Declaration
  - Execution Monitoring
  - Delivery Validation
- Map each stage to concrete nodes/logic in the graph; show when checkpoints occur.

10) Sample Runs (sample_runs.json)
- Valid JSON containing at least two examples:
  - One with "requires_approval": true and expected tool pause.
  - One with "requires_approval": false (no tool pause).
- Each example includes ordered "expected_flow" array of node names (strings).

Scoring Guidance (human grader):
- Completeness of required elements (pass/fail).
- Clarity and coherence of routing and exit conditions.
- Realism of tool stubs and safety conformance.
- Alignment of docs with rubric-required sections and spec.yaml.