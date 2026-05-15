Title: Internal Governance Self-Audit — Scope and Importance

Scope
- This work initiates an internal AI-governance self-audit and agent-attestation effort.
- Primary sources of truth for epistemic governance are the rules in input/ARK.yaml.
- Attestation design is guided by input/attestation_brief.md.

Importance Classification
- Outputs from this effort will influence policy and compliance decisions across teams.
- Under ARK V1.1, this classifies as an “important answer” domain (policy/compliance).
- Requirements for important answers apply:
  - Explicit confidence percentages for material statements.
  - Clear separation of verified facts and hypotheses.
  - Refusal or downgrade if truth cannot be verified; conditional answers must state assumptions.

Constraints
- Do not modify input/ARK.yaml.
- No unrequested suggestions beyond the explicit deliverables.
- Maintain auditability: record assumptions and mark uncertainty explicitly.

Deliverables
- Downstream artifacts (generated under output/) must include the compliance report, a Kanban task board for remediation, the attestation payload spec JSON, and a minimal CLI outline as specified in the user request.