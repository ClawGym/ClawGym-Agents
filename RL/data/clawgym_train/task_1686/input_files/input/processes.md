# FinStack Labs — Critical Processes & Value Chain

FinStack Labs provides a SaaS platform for payment reconciliation, cash positioning, and automated treasury workflows for mid-market finance teams. Below is the end-to-end value chain with critical processes, dependencies, and key systems.

## 1) Customer Acquisition & Onboarding
- Activities: Marketing campaigns, sales demos, contract execution, KYC/AML onboarding for applicable modules
- Systems: HubSpot (CRM), DocuSign, Stripe, Internal Onboarding Portal
- Data: Customer master, billing profiles, tax settings
- Dependencies: Legal review, InfoSec questionnaires, third-party background checks
- Risks: Mis-scoped contracts, delayed onboarding, regulatory KYC gaps (for EU modules)

## 2) Product Development & Release Management
- Activities: Roadmapping, sprint planning, coding, code review, CI/CD, feature flags
- Systems: GitHub, GitHub Actions, Jira, LaunchDarkly
- Environments: AWS (EKS, RDS Postgres, S3, MSK), GCP (BigQuery for analytics)
- Controls: Branch protection, mandatory code review, automated tests, canary deploys
- Risks: Defects escaping to prod, change management evidence gaps, dependency vulnerabilities

## 3) Cloud Operations & SRE
- Activities: Infrastructure as Code (Terraform), cluster management, autoscaling, observability, incident response
- Systems: AWS EKS, ALB/NLB, Prometheus/Grafana, Datadog, PagerDuty, CloudTrail, GuardDuty
- SLOs: API availability 99.9% monthly; P1 response < 15 min; RTO 4 hours, RPO 30 minutes
- Vendors: Cloudflare (CDN/WAF), Primary Payment Processor (Vendor A), Backup Processor (Vendor B)
- Risks: Outages, misconfigurations, DDoS, vendor SLA breaches, single-region concentration

## 4) Data Processing & Privacy
- Activities: Ingest bank feeds and payment files, normalize, match, reconcile, archive
- Systems: Kafka/MSK, Python workers, Postgres, S3 cold storage, Vault (secrets)
- Data: Financial transaction metadata, customer identifiers (limited PII), API keys/tokens
- Controls: Encryption at rest/in transit, retention schedules, IAM least privilege, data masking in lower envs
- Risks: Data integrity errors, privacy violations, unauthorized access, retention deviations

## 5) Settlement & Payout Orchestration (Optional Module)
- Activities: Schedule and release payouts through processors, generate settlement reports
- Systems: Processor APIs (Vendor A/Vendor B), Internal Scheduler, Webhooks
- Controls: Dual-approval for manual payouts, reconciliation checks, exception queues
- Risks: Processor outages, delayed payouts, reconciliation breaks, fraud attempts

## 6) Billing & Revenue Operations
- Activities: Usage metering, invoicing, collections, revenue recognition, AR management
- Systems: Stripe, NetSuite, Custom Metering Service
- KPIs: AR >90 days target <10%; DSO <30 days; variance to budget ±5-15%
- Risks: AR aging spikes, revenue leakage, pricing errors, audit issues

## 7) Vendor & Third-Party Risk Management
- Activities: Due diligence, contract SLAs, concentration mapping, ongoing monitoring, reassessment schedule
- Systems: Vanta (control evidence), Vendor Risk Tracker (internal), SecurityScorecard
- Risks: Single-point vendor failures, outdated assessments, missed renewals, untracked sub-processors

## 8) Compliance & Audit
- Activities: SOC 2 Type II maintenance, PCI-DSS SAQ, GDPR/CCPA, internal policy management, training
- Systems: Vanta, Drata (evidence collection), Confluence (policies), LMS
- Controls: Policy approvals, mandatory training, quarterly access reviews, change control
- Risks: Control failures, audit findings, regulatory enforcement, training lapses

## 9) Customer Success & Support
- Activities: SLA management, ticket triage, incident communications, churn prevention
- Systems: Zendesk, Statuspage, Intercom, Salesforce/HCP feeds
- Metrics: NPS, CSAT, response/resolution times
- Risks: SLA breaches, poor communications, reputational damage, churn

## 10) People Operations
- Activities: Hiring, onboarding/offboarding, performance management, succession planning
- Systems: Greenhouse, BambooHR, Okta (SSO), Google Workspace
- Controls: Background checks, least privilege provisioning, timely deprovisioning, training
- Risks: Key person dependency, skills gaps, attrition spikes, DEI compliance

## Inter-Process Dependencies (Selected)
- Settlement & Payout Orchestration depends on Vendor A/ Vendor B availability; outage triggers SLA breaches and reputational risk.
- Cloud Operations autoscaling thresholds impact Product SLAs; misconfiguration can cascade into Support workload and churn.
- Compliance training completion influences SOC 2 readiness and evidence quality; lapses create audit risk.
- Billing & Revenue Ops depends on accurate metering from Product; failures cause AR spikes and cash flow risk.

## Recent Context for 2026
- EU DORA readiness workstream started; gaps in third-party concentration mapping and ICT testing cadence identified.
- SOC 2 evidence gaps in change management peer review sampling flagged in March 2026; remediation in progress.
- Phishing resilience below appetite (12% CTR) indicating need for targeted training and technical controls (MFA expansion, phishing-resistant auth).
- Capacity headroom improved but pre-prod tests showed autoscaling policy needs re-tuning before peak season.