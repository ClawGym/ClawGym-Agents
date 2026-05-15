# Project Brief: Multi-Region Payments & Subscriptions Service (Codename: OrbitPay)

## Purpose
Build a backend service that provides a unified API for payments, subscriptions, invoicing, refunds, and notifications across multiple regions. The service must decouple core business logic from external providers so we can rapidly swap integrations for cost, compliance, and reliability reasons without changing domain code.

## Scope (MVP → Phase 1)
- Customers & Payment Methods (tokenized by providers; we do not store PANs)
- Subscriptions (plans, trials, proration rules, status transitions)
- Invoices & Charges (one-time and recurring)
- Refunds (full/partial)
- Notifications (email and SMS for receipts, dunning, trial reminders)
- Tax Calculation (external service)
- Fraud Checks (pre-charge risk scoring)
- Analytics events (outbound to data pipeline)

## Why Now
- Entering 6 new countries within 2 quarters with varying payment rails and compliance needs.
- Procurement wants leverage to renegotiate PSP contracts by enabling A/B testing and regional routing.
- Marketing requires rapid iteration on communication providers to improve deliverability and reduce SMS costs.

## External Interaction Model
- Inbound:
  - REST API for checkout and admin operations
  - Async commands via message bus (e.g., invoice generation, dunning retries)
- Outbound:
  - Payment processors (Stripe, Adyen, Braintree, and regional PSPs)
  - Email (SendGrid/Mailgun), SMS (Twilio/Vonage)
  - Tax calculation (TaxJar/Avalara)
  - Fraud scoring (Sift/alternatives)
  - Analytics (Segment/RudderStack)
  - Webhooks to upstream CRM/ERP

## Business Rules (Examples)
- Subscription lifecycle: pending → active → past_due → canceled (grace period configurable)
- Proration requires plan price/existing period calculations
- Dunning schedule: 3 retries over 7 days; escalate notifications
- Idempotency for payments and refunds (idempotency keys on inbound commands)
- Regional routing: choose payment gateway per market and method availability
- No card data storage in our system (PSP tokens only)

## Success Criteria
- Swap a payment gateway or notification provider without touching domain rules
- >99.9% monthly availability for charge/create subscription
- P95 latency: <250ms for reads, <500ms for charge attempts (excluding provider latency)
- Comprehensive unit tests on core domain and use cases; adapters mocked

## Notes on Domain Complexity
- Moderate domain complexity (subscription proration, dunning, state transitions)
- Complexity is driven more by external integrations and their variability than by deeply intricate domain models
- Expect provider-specific quirks and frequent API/version changes

## Constraints & Considerations
- Language: Python (async-first)
- Database: PostgreSQL (transactions, outbox for reliable events)
- Observability: structured logs, metrics, traces
- Compliance: PCI SAQ A; no storage of raw PANs; data minimization
- Team: ~7 engineers; weekly releases; rapid provider experiments
- Key design goal: “swap integrations, keep domain stable”

---

Decision Inputs Summary:
- Multiple external integrations (payments, email, SMS, tax, fraud, analytics)
- Several of these integrations change frequently due to regional rollout and experiments
- Maintainability and testability are high priorities
- Domain is meaningful but not so complex to mandate full-blown DDD bounded contexts in MVP