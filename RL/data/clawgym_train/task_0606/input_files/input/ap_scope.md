# AP Automation Pilot (Q3) — Scope and Acceptance Criteria

This pilot establishes a production-ready accounts payable (AP) workflow spanning invoice intake, matching/exception handling, approval routing, payment optimization, vendor master data standards, and month-end close with fraud controls. The goal is to reduce invoice processing cost and cycle time while improving control effectiveness and discount capture.

Parent task (project):
- Title: AP Automation Pilot (Q3)
- Requested status: ready

Requested starting statuses for each workstream (child tasks):
- Invoice Processing Pipeline — ready
- Approval Routing Design — backlog
- Payment Optimization Setup — backlog
- Vendor Master Data Standards — icebox
- Month-End Close & Fraud Controls — icebox

Use input/assignees.json for owners, input/priorities.json for the “priority” metadata value, input/tags.yaml for tag attachments, and input/dependencies.yaml to enforce sequencing and risk controls. Each child should include relevant scope and acceptance criteria below as its task body.

---

## Invoice Processing Pipeline
Requested status: ready

Scope:
- Build the end-to-end intake → validation → 3-way match → exception management → post-to-ERP flow.
- Configure OCR for header and line-level fields (vendor name/ID, invoice number/date, PO, line items, quantities, unit price, taxes).
- Implement duplicate detection using vendor + amount + invoice number + date.

Acceptance criteria:
- OCR extraction accuracy ≥98% on a 50-invoice pilot set (header fields) and ≥95% for line items.
- 3-way match with tolerances: price ±2%, quantity ±1 unit; unmatched items route to exception queue with reason code.
- Duplicate prevention flags any invoice matching vendor+invoice number OR vendor+amount+date within 90 days.
- Exception queue with SLA timers and reassignment; audit trail for state changes.
- Straight-through processing (STP) baseline ≥60% on pilot vendors with target roadmap to 80%.
- Processing SLA: median time from intake to approval-ready ≤2 business days.

Definition of done:
- Deployed pipeline integrated with approval routing handoff and basic dashboards (throughput, STP, exception rate).

---

## Approval Routing Design
Requested status: backlog

Scope:
- Design conditional routing by amount thresholds and risk flags.
- Define roles, SLAs, escalations, and out-of-office delegation.

Acceptance criteria:
- Routing table: <$1,000 auto-approve if 3-way matched; $1,000–$10,000 manager (2-day SLA); $10,000–$50,000 director/VP (3-day SLA); $50,000+ CFO (5-day SLA).
- Approver notifications with reminders at 50% and 90% of SLA; auto-escalation after SLA breach.
- Audit log: who/when/what for approvals, reassignments, and comments.
- Fallback path for missing-PO invoices to business owner with variance rationale required.

Definition of done:
- Routing rules configurable without code; end-to-end approval trial on 10 invoices with pass/fail evidence.

---

## Payment Optimization Setup
Requested status: backlog

Scope:
- Implement discount capture logic (e.g., 2/10 Net 30) and payment scheduling orchestration.
- Pilot virtual card or early-pay programs for eligible vendors.

Acceptance criteria:
- Discount engine computes break-even and annualized return; flags optimal pay date per vendor/invoice.
- Scheduler staggers payments to meet cash targets while maximizing discount capture.
- Vendor eligibility matrix (terms, acceptance of card/early pay, risk tier).
- Baseline simulation from last 3 months’ invoices estimating savings; pilot yields ≥50% capture of available discounts.

Definition of done:
- Production-ready payment calendar + dashboard showing discount opportunities, realized savings, and missed opportunities with reasons.

---

## Vendor Master Data Standards
Requested status: icebox

Scope:
- Define vendor master data dictionary and validation rules.
- Implement onboarding requirements (TIN verification, W-9/W-8BEN collection) and bank change controls.

Acceptance criteria:
- Data dictionary covering legal name, TIN, address, currency, terms, bank info, 1099 flag, GL defaults.
- TIN verification protocol, W-9/W-8BEN collection, and annual recertification.
- Dedupe rules (match on TIN + name similarity threshold); no duplicate vendors in pilot set.
- Bank change control with callback verification to a known phone number and four-eyes approval.

Definition of done:
- Vendor master checklist operationalized; 100% of pilot vendors validated and documented.

---

## Month-End Close & Fraud Controls
Requested status: icebox

Scope:
- Strengthen close process and implement anti-fraud controls integrated with AP flows.

Acceptance criteria:
- Positive pay for checks; ACH filters and anomaly detection for outbound payments.
- AP subledger-to-GL reconciliation report; aging and GR/IR accrual checklist.
- Segregation of duties: no single user may create vendor + approve invoice + release payment.
- 1099 vendor tracking validated; exception report for missing tax forms.
- Audit reports: who approved, override reasons, and late approvals.

Definition of done:
- Close checklist executed on pilot month with zero unreconciled differences and fraud controls verified via test cases.

---

Dependencies and sequencing:
- Approval Routing Design depends on Invoice Processing Pipeline.
- Payment Optimization Setup depends on Approval Routing Design.
- Vendor Master Data Standards depends on Invoice Processing Pipeline.
- Month-End Close & Fraud Controls depends on Vendor Master Data Standards.

Follow input/dependencies.yaml to enforce these relationships and reduce risk of rework.

---

Notes:
- Use tags from input/tags.yaml and align with the canonical tag priority list (bug, security, improvement, test, performance, refactor, docs).
- Set metadata key “priority” from input/priorities.json exactly (critical, high, medium, low).
- Assign owners from input/assignees.json; share work where beneficial for cycle time and cross-training.