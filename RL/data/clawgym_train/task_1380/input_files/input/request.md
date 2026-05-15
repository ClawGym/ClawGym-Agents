# Data Quality Audit for CSV Logs

Project brief:
Produce a small, high-quality documentation set for a data quality audit focused on CSV-formatted application logs. The goal is to plan and document the audit process and its verification, using only local processing and the constraints provided. No external network access is required.

Objectives:
- Clarify and structure requirements based on this request and constraints.json.
- Create a concise, dependency-aware plan with three tasks (T1, T2, T3).
- Execute the tasks to produce deterministic, text-only deliverables.
- Verify outputs using a 14-item checklist and record a final verdict.

Input files:
- input/request.md (this file)
- input/constraints.json (constraints and limits)

Output structure and content rules (save everything under output/workspace/orch-001/):

1) Phase 0 — requirements.md
- Sections with clear headings in this order: Scope, Constraints, Deliverables, Feasibility.
- In Scope, restate the project title exactly: “Data Quality Audit for CSV Logs”.
- In Constraints, incorporate limits from input/constraints.json.
- In Deliverables, explicitly list the files to be produced in Phases 1–3.
- In Feasibility, state that the task is feasible using only the provided input files and local processing.
- The file must end with a final line that literally reads: “User approval: APPROVED”.

2) Phase 1 — final-plan.md
- Include a concise overview and a clearly enumerated task list for exactly 3 tasks named T1, T2, and T3.
- Specify dependencies with the exact line: “Dependencies: T3 depends on T1 and T2”.
- Include a cost/safety section reflecting input/constraints.json that contains these literal substrings somewhere in the file:
  - “budget tier: caution”
  - “max concurrent: 3”
  - “retry limit: 3”
- Include a “Rollback strategies” section with at least one bullet for each task (T1, T2, T3).

3) Phase 2 — tasks/
Create these files with the exact first line and content rules:
- output/workspace/orch-001/tasks/task-1/output.md
  - First line exactly: “Task-1 Completed”
  - Must mention the project title: “Data Quality Audit for CSV Logs”.
- output/workspace/orch-001/tasks/task-2/output.md
  - First line exactly: “Task-2 Completed”
  - Must mention both “max concurrent agents: 3” and “budget tier: caution”.
- output/workspace/orch-001/tasks/task-3/output.md
  - First line exactly: “Task-3 Completed”
  - Must include the phrase “Integration summary” and the word “Consolidated”.

4) Phase 3 — verification/
Create these files:
- output/workspace/orch-001/verification/completeness-report.md
- output/workspace/orch-001/verification/accuracy-report.md
- output/workspace/orch-001/verification/hallucination-report.md
  - Must contain exactly 14 lines, formatted exactly as: “H-1 PASS” through “H-14 PASS” (one per line).
- output/workspace/orch-001/verification/integration-report.md
- output/workspace/orch-001/verification/final-verdict.md
  - Must contain the word “PASS” and include a line “regressions: 0”.

5) State tracking — orche-state.json
Create output/workspace/orch-001/orche-state.json with at least:
- "taskId": "orch-001"
- "phase": 3
- "status": "completed"
- "retryCount": 0
- "maxRetries": 3
- "tasks": an array of three objects for task-1, task-2, task-3, each with status "completed" and output paths that match the actual files written in Phase 2.

General rules:
- Use only the information from input/request.md and input/constraints.json.
- Do not include any TODO/TBD placeholders in any file.
- Save all outputs only under output/workspace/orch-001/ as specified.
- All files must be non-empty and internally consistent.

Suggested audit focus areas for CSV logs (for context only; do not require code execution):
- Schema consistency across files (column presence/order).
- Data type validation (e.g., timestamps, integers, floats).
- Missing values and null-like tokens.
- Duplicate records and key uniqueness.
- Timestamp format normalization and timezone assumptions.
- Value range checks and categorical domain validity.
- Row-level integrity (e.g., delimiter and quoting correctness).

Success criteria:
- All required files exist with exact literals where specified.
- The verification checklist contains exactly 14 lines from H-1 PASS to H-14 PASS.
- The final verdict indicates PASS and “regressions: 0”.
- The state file references correct, existing paths and indicates completion.

Execution environment assumptions:
- Local, text-only processing.
- No external network access.
- Use only the provided inputs to derive constraints and produce outputs.