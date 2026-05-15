Company overview
- Team size: 120-person B2B SaaS company
- Customers: Majority in the EU (70%+ revenue), mix of SMB and mid-market
- Industry: Workflow and analytics platform for supply-chain operations
- Timeline: Target go-live in 4 months with phased rollout; full production by month 6

Current data & stack
- Clouds: Multi-cloud (AWS primary for app; GCP for analytics pipelines; limited Azure for identity and several partner integrations)
- Data systems:
  - Snowflake (customer 360 warehouse; >20 TB compressed)
  - Postgres (app DBs; ~6 instances)
  - Kafka (Confluent-managed; ~200 MB/s peak ingress)
- Identity: Okta and Azure AD (federation needed)
- Languages: Node.js, Python, Java microservices
- Data volume targets (year 1):
  - Master records: ~40M customer profiles; ~15M account/org records; ~75M contact/endpoint records
  - Ingest rate: bursty streams; 5–15K events/sec peak
  - Data quality: current duplicate rate ~7–10%

Business objectives
- Consolidate and govern master data across Snowflake, Postgres, and event streams
- Real-time/entity resolution for customer, account, and contact domains
- GDPR-compliant data handling with EU-only residency option
- Reduce duplicate rate below 1.5% within 6 months
- Improve auditability and lineage for regulatory/customer reviews

Must-haves
- Security & compliance
  - SOC 2 Type II and ISO 27001 strongly preferred
  - GDPR DPA and EU data residency (EU-only processing + EU backups)
  - SSO (SAML and OIDC); SCIM provisioning preferred
  - Fine-grained RBAC and audit logs
  - Encryption in transit and at rest; CMEK preferred but not strictly required
- Technical fit
  - Connectors for Snowflake and Postgres
  - Native/first-class streaming ingestion (Kafka) with near real-time mastering
  - APIs with strong documentation; SDKs for Node.js and Python at minimum
  - Support for AWS and GCP now; Azure support desirable within 12 months
  - Survivorship rules, golden record management, and lineage tracking
- Support & SLAs
  - 99.9%+ uptime SLA
  - 24x7 P1 support; ≤1 hour response target
  - Implementation assistance and training
- Lock-in & portability
  - Bulk export without penalties; export of models, rules, and lineage
  - Avoid proprietary traps where possible (open/portable rule definitions)
  - Clear termination assistance
- Pricing & term
  - 12-month term preferred; renewal flexibility
  - Year 1 TCO target: $60k–$90k, including necessary connectors and support
  - Predictable pricing; minimal hidden/egress/overage fees

Nice-to-haves
- Customer-managed keys (CMEK) for EU regions
- Data mesh friendly (domain-oriented governance)
- Roadmap: Delta Lake support, Azure-native connectors by Q3–Q4 2026
- Consent/PII handling aid for GDPR workflows

Constraints & risks
- We cannot store or back up personal data outside the EU due to contractual commitments
- GCP support is required immediately for analytics pipelines; Azure support acceptable within a year
- Lock-in risk tolerance is low: we must be able to export data and rules if we exit
- Budget cannot exceed $100k in year 1 without CFO approval

Evaluation notes
- Shortlist: DataForge MDM and CleanStack MDM
- We will weigh technical fit and security/compliance highest; pricing and lock-in next; the rest baseline
- Evidence basis should come from vendor profiles and aggregated customer feedback included in this package

Acceptance criteria by go-live
- Kafka ingestion to golden records < 5 minutes end-to-end (p95)
- Duplicate rate reduced to ≤2% in first 3 months; ≤1.5% by month 6
- EU-only data residency confirmed by signed DPA; no replication of backups outside EU
- SSO via Okta and Azure AD (SAML and OIDC) operational
- Successful exports of data and rules tested as part of exit-readiness drill