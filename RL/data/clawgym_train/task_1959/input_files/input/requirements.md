# Technical Spec Review — Team Process Overview

This document defines how our team reviews technical specs, design docs, RFCs, and architecture proposals. It sets goals, acceptance criteria, tone, when to use the process, a standardized report template, and objectively checkable items we’ll use for automation later.

## Goals
- Catch design risks early, before expensive implementation work.
- Align proposed designs with functional and non-functional requirements (security, privacy, reliability, performance, observability).
- Document decisions, trade-offs, and open questions to reduce ambiguity.
- Provide actionable feedback with severity, owners, and dates so changes get made.

## When to use this process
Trigger this process when any of the following are true:
- A new feature or service is proposed (design doc / spec ready for review).
- A substantial change to an existing system is planned (e.g., data model changes, protocol version upgrades, auth flows).
- An architecture review board (ARB) or RFC requires sign-off.
- Cross-team integration impacts data flow, PII handling, or SLAs.
- You see phrases like: “spec”, “design review”, “architecture review”, “RFC”, “ADR”, “proposal”, “tech design”, “request for comments”, “solution overview”.

Non-triggers:
- Small, low-risk code changes (minor refactors, copy tweaks).
- Post-implementation retros (use the postmortem template instead).

## Tone and style
- Concise, neutral, constructive.
- Imperative mood for recommendations (“Clarify X…”, “Add rate limiting…”).
- Avoid hype (“amazing”, “game-changing”); prefer specific evidence and measurable targets.
- Use bullet lists for risks and action items to keep them scannable.

## Inputs expected
- The spec text or a link, plus any diagrams, sequence flows, data contracts, and acceptance criteria.
- Context: business goals, constraints, stakeholders, target release window.
- Any prior decisions (ADRs), experiments, or metrics that inform the design.

## Deliverable
A standardized “Technical Spec Review Report” that:
- Follows the section structure and heading names below exactly.
- Includes at least the required counts and fields for risks, checklists, actions, and decisions.
- States a clear status: Approve / Changes Requested / Blocker.

## Required sections and minimum contents
- Title and Metadata: Title, Spec Links, Reviewer, Date (YYYY-MM-DD), Status.
- Executive Summary: 120–180 words summarizing the proposal, scope, and key concerns.
- Architecture & Data Flow: describes components and data movement; call out trust boundaries and external dependencies.
- Requirements Traceability: map each requirement to a design element or artifact.
- Risk Assessment: at least 3 risks, each with Owner, Severity (High/Medium/Low), Likelihood, Impact, and Mitigation.
- Non-Functional Requirements (NFR) Checklists: at least 6 total checklist items across Security, Privacy, Reliability, Performance, Observability; each with Y/N/NA and Notes.
- Testing & Rollout: include at least 2 testable acceptance tests and a rollout/rollback plan.
- Open Questions: at least 1, up to 10, with a plan to resolve.
- Action Items: at least 3 items, each with Owner and Due (YYYY-MM-DD).
- Decision Log: at least 2 decisions with Rationale and Date.
- Appendices: optional, for diagrams, assumptions, or links.

## Standard report template (must be followed)
Copy and fill this exact structure. Use the same headings and subheadings.

# Technical Spec Review Report
- Title: <spec title>
- Spec Links: <URL(s) or path(s)>
- Reviewer: <name> | Date: <YYYY-MM-DD>
- Status: <Approve | Changes Requested | Blocker>

## Executive Summary (120–180 words)
<one paragraph in the target range>

## Architecture & Data Flow
- Components:
  - <component 1> — <role>
  - <component 2> — <role>
- Data flows:
  - <source> → <destination> via <protocol>; <authn/authz>; <PII?>; <encryption?>
- Trust boundaries:
  - <boundary and implications>
- External dependencies:
  - <service/vendor/version and risks>

## Requirements Traceability
| Requirement ID | Requirement Description | Design Element / Evidence |
|---|---|---|
| R1 | <desc> | <component/file/diagram/link> |
| R2 | <desc> | <component/file/diagram/link> |

## Risk Assessment
- Risk: <summary>
  - Owner: <name/team>
  - Severity: <High | Medium | Low>
  - Likelihood: <High | Medium | Low>
  - Impact: <user/data/latency/ops/etc>
  - Mitigation: <specific action and fallback>

- Risk: <summary>
  - Owner: <name/team>
  - Severity: <High | Medium | Low>
  - Likelihood: <High | Medium | Low>
  - Impact: <...>
  - Mitigation: <...>

- Risk: <summary>
  - Owner: <name/team>
  - Severity: <High | Medium | Low>
  - Likelihood: <High | Medium | Low>
  - Impact: <...>
  - Mitigation: <...>

## Non-Functional Requirements Checklists
### Security
- [Y/N/NA] <item> — Notes: <detail>
### Privacy
- [Y/N/NA] <item> — Notes: <detail>
### Reliability
- [Y/N/NA] <item> — Notes: <detail>
### Performance
- [Y/N/NA] <item> — Notes: <detail> (include a target, e.g., p95 latency < 300ms)
### Observability
- [Y/N/NA] <item> — Notes: <detail>

## Testing & Rollout
- Acceptance Test 1: <description; testable; pass/fail criteria>
- Acceptance Test 2: <description; testable; pass/fail criteria>
- Rollout Plan: <staged rollout, canary %, metrics guardrails, rollback trigger>

## Open Questions
1) <question> — Owner: <name> — Plan: <how to resolve>

## Action Items
- <action> — Owner: <name> — Due: <YYYY-MM-DD>
- <action> — Owner: <name> — Due: <YYYY-MM-DD>
- <action> — Owner: <name> — Due: <YYYY-MM-DD>

## Decision Log
- Decision: <what> — Rationale: <why> — Date: <YYYY-MM-DD>
- Decision: <what> — Rationale: <why> — Date: <YYYY-MM-DD>

## Appendices
- Diagrams: <links or paths>
- Assumptions: <list>
- References: <links>

## Objectively checkable acceptance criteria
Automations may verify:
- Required headings exist exactly as in the template.
- Executive Summary word count between 120 and 180 inclusive.
- At least 3 risks present with Severity and Mitigation fields.
- At least 6 total NFR checklist items across Security/Privacy/Reliability/Performance/Observability.
- At least 2 acceptance tests specified under Testing & Rollout.
- At least 3 action items with Owner and Due in YYYY-MM-DD format.
- At least 2 decisions in Decision Log with Rationale and Date.
- Requirements Traceability table with at least 2 rows.

## Edge cases and guidance
- Missing or ambiguous requirements: call them out in Open Questions and propose how to validate.
- Multiple services or teams: ensure ownership is explicit per risk and action.
- PII or regulated data: confirm lawful basis, minimization, retention, and data subject rights paths.
- External vendors: identify SLAs, shared responsibility, incident handling, and versioning.
- Performance targets: state concrete thresholds (e.g., p95 latency < 300ms; error rate < 0.1%).
- Observability: ensure log redaction of secrets, structured logs, alert thresholds, and trace coverage.

## Example checklist items
- Security: Input validation for <endpoint> implemented server-side; rate limiting at <value>/min.
- Privacy: PII fields encrypted at rest (AES-256) with KMS-managed keys; data retention < N days.
- Reliability: Retry with exponential backoff and idempotency keys on write APIs.
- Performance: p95 end-to-end < 300ms under <QPS> with <payload size>.
- Observability: Traces include user_id hash and request_id; dashboards for p95/p99, error rate, saturation.

---

By following this process and template, reviews become consistent and automatable. Future evaluation scripts will check structure, counts, and field presence to measure quality over time.