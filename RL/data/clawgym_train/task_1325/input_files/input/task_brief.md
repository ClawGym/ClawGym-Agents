# Task Brief — ONB-101: Create a Single-File Engineer Onboarding Document

Objective
Create a concise, practical onboarding document for new engineers joining Northwind Apps. The document should get a new hire productive on Day 1 with clear setup steps, access instructions, standards, and team workflows. It must be written as a single Markdown file named ONBOARDING.md and include a brief “How to verify” section at the bottom.

Context
- Company: Northwind Apps (product-focused SaaS)
- Team: Backend + Frontend + Ops, async-first with light sync rituals
- Tools: GitHub, Linear (tickets), Notion (knowledge), Slack (async-first comms), CI/CD via GitHub Actions, staging/prod on Render, secrets via 1Password/Env vars

Deliverable
- A single Markdown file: output/artifacts/ONB-101/ONBOARDING.md
- Length: Approximately 1–2 pages (about 700–1200 words)
- Audience: New engineers and ops hires (first week)

Required Sections (headings must appear in the document)
1) Welcome and Values (tone: friendly, direct)
2) Quick Start — First-Day Checklist (numbered list)
3) Access and Tools (GitHub, Linear, Notion, Slack, CI/CD, Environments)
4) Local Development Setup (copy-paste commands; placeholder secrets like <TOKEN>)
5) Branching, Commits, and Pull Requests (conventions and PR checklist)
6) Coding Standards and Testing (brief rules; how to run tests locally/CI)
7) Ticket Workflow (Inbox → Assigned → In Progress → Review → Done; when to escalate)
8) Meetings and Communication (async-first, response-time expectations)
9) Security and Secrets (no secrets in code; rotations; least privilege)
10) Support and Escalation (who/where to ask; expected context in questions)
11) How to verify (explicit steps to confirm onboarding doc completeness and location)

Acceptance Criteria (must be met)
- File path and name: output/artifacts/ONB-101/ONBOARDING.md
- Contains all required section headings listed above
- Contains copy-paste setup instructions for local dev (e.g., git clone, environment setup, test commands)
- Includes clear PR checklist (linked to standards) and a brief testing section
- “How to verify” section at bottom, with steps that a reviewer can follow without additional context
- Plain English, consistent H1/H2/H3 hierarchy, actionable checklists where appropriate
- No real secrets; use placeholders like <GITHUB_TOKEN> and <RENDER_API_KEY>
- Friendly but precise tone; avoid jargon when a simpler term exists

Process Constraints (followed by the multi-agent workflow)
- Use Spec → Review → Build → Test pattern
- The spec must include: “Task ID: ONB-101” and “Output Path: output/artifacts/ONB-101”
- The builder cannot approve their own work; a reviewer must write the review notes and reference the artifact path
- The orchestrator must mark “Done”
- Record a decision relevant to formatting or scope (e.g., heading style or inclusion of a first-day checklist), using a structured decision log
- All lifecycle transitions and comments must be recorded in output/board.json, including a builder handoff comment with these five labels: “What was done”, “Where artifacts are”, “How to verify”, “Known issues”, “What’s next”

Verification Guidance (for the reviewer)
- Confirm the file exists at output/artifacts/ONB-101/ONBOARDING.md
- Check presence of all required section headings
- Follow “How to verify” steps to validate completeness
- Ensure tone, length, and clarity meet expectations
- Ensure no secrets; placeholders only

Key Details to Include in the Document
- Tool links may use example.com placeholders (e.g., https://notion.example.com)
- Example repo name: northwind/nw-app
- Example branch naming: feature/<ticket-id>-<slug>
- Test command examples: npm test or pytest, with a short note to adapt per stack
- CI note: PRs require at least one passing review and CI green before merge

Ambiguity Handling
If any acceptance criterion is ambiguous (e.g., exact testing stack), make a sensible choice, document it in the decision log, and proceed.

Deliverable Paths Summary
- Spec: output/specs/ONB-101-spec.md
- Artifact: output/artifacts/ONB-101/ONBOARDING.md
- Review: output/reviews/ONB-101-review.md
- Decision: output/decisions/ONB-101-decision.md
- Lifecycle: output/board.json

Success Definition
A reviewer can follow the document to complete first-day setup without external help, and the workflow artifacts satisfy the path, authorship, and lifecycle constraints.