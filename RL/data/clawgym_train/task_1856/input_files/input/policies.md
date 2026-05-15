# Customer Support Policies

Last Updated: 2026-04-12
Owner: Customer Experience + Finance

## 1) Refund Policy

- Auto-approve refunds up to $50 if:
  - Order delivered within last 30 days
  - Clear defect or service failure documented
  - Confidence >= 0.70

- Manager approval required for refunds > $50 and <= $200.
  - Route to oncall_manager@company.com (SLA: 2 business hours)

- Finance approval required for refunds > $200.
  - Route to support_team@company.com and finance approver list (SLA: 1 business day)

- Hard cap per incident: $500 (never auto-approve; escalate)

- Require order verification before any refund or cancellation:
  - Match order_id + customer_email OR order_id + last4 of payment (read-only)

- Refunds must be issued via OMS refund API. PaymentsService and LedgerDB are read-only for the AI.

## 2) Cancellations

- Allowed only if order status is "Created" or "Picking"
- If "Shipped" or beyond, require manager approval or offer goodwill credit <= $25 (within $50 auto cap)
- Confidence < 0.60 → escalate before attempting cancellation

## 3) Financial Systems Access

- AI agent is READ-ONLY to:
  - PaymentsService
  - LedgerDB

- Any write (POST/PUT/PATCH/DELETE) attempts to these systems are policy violations and must be blocked and escalated to security_team@company.com.

## 4) Safety & Monitoring Targets

- Decision quality (rolling 5–10 min): target >= 0.93, alert if < 0.92 for 10 min; page on call if < 0.90
- Error rate (rolling 5 min): target <= 0.03, alert if > 0.04; auto-rollback or pause if > 0.05
- Avg latency: target < 3000 ms; alert if > 3000 ms for 10 min
- Token usage budget:
  - Expected daily ~ 200k–230k tokens (based on last 14 days)
  - Hourly soft limit: 15,000 tokens; alert if > 20,000 tokens/hour; anomaly if > 3x hourly baseline
- Confidence:
  - Min for autonomous actions: >= 0.70
  - Escalate if confidence < 0.60 on any action with monetary or irreversible impact

## 5) Escalation Paths

- Cost exceeded thresholds → oncall_manager@company.com
- Policy violation (e.g., attempted write to financial system) → security_team@company.com
- Low confidence high-impact decisions → support_team@company.com
- Anomaly (burst tokens, unusual API mix) → oncall_manager@company.com and security_team@company.com (if related to access)

## 6) Audit Requirements

Every autonomous decision must be logged with:
- action
- reasoning
- constraints_checked
- information_considered (order details, policy refs)
- approver (or null)
- outcome
- confidence
- alternatives considered