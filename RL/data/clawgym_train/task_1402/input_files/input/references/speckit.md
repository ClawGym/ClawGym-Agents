# Spec-Kit Templates and Format

Use this reference to generate implementation-ready artifacts.

1) memory/constitution.md
- Purpose: Non-negotiable principles and tradeoff rules.
- Structure:
  Title
  Principles (bulleted, testable)
  Tradeoffs (scope/time/cost)
  Guardrails (security, compliance, data)
  Decision rights (who decides what)

2) specs/<feature>/spec.md
- Sections:
  Title and Summary
  Vision and Scope (in/out)
  User Scenarios (US1, US2, …) with Given/When/Then
  Functional Requirements
  Non-Functional Requirements
  Data Model (key entities)
  Interfaces/Contracts (reference files in contracts/)
  Acceptance Criteria (trace back to scenarios)
  Risks and Mitigations
  Success Criteria
  Parked Items (use [NEEDS CLARIFICATION] max 3)

3) specs/<feature>/data-model.md
- Entities with fields (name, type, constraints)
- Relationships (ER bullets)
- State Transitions (diagrams in text or bullet sequences)
- Validation Rules

4) specs/<feature>/contracts/*.md
- One file per interface (API endpoint or event or CLI)
- Include: endpoint paths or topic names, request/response schemas, error codes, auth, examples

5) specs/<feature>/tasks.md
- Format per task:
  - [ ] [T###] [P] [US#] Description `path/to/file`
  Where:
    T### = task id
    [P] = phase code (A=Alpha, B=Beta, GA=General Availability)
    [US#] = user story reference (e.g., [US1])
- Group tasks by dependency order; mark parallelizable groups.

6) specs/<feature>/checklists/requirements.md
- Checklist derived from acceptance criteria:
  - [ ] Req-### Short statement (reference to US# and Given/When/Then)
- Avoid vague language; ensure testability.

7) Cross-Validation Rules
- Every user scenario has at least one task.
- Every entity appears in at least one contract or is justified as internal-only.
- “[NEEDS CLARIFICATION]” max 3 per artifact.
- Acceptance criteria are measurable (latency, availability, etc.).