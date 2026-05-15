Title: Senior Platform Engineer
Team: Platform Engineering
Hiring Manager: Jordan Patel (Director of Engineering)
Location: Remote-first, global team (require 4 hours overlap with US Eastern Time)
Company Stage: Series B SaaS — Data analytics platform for mid-market enterprises
Team Size: 45 engineers total; Platform Engineering team of 4 (you + 3)
Reporting: Directly to Director of Engineering; partners with Security, SRE, and Backend Leads

Mission
Enable product teams to ship reliably, securely, and fast by providing a paved road (platform) for build, deploy, and runtime — with clear SLOs and guardrails.

Environment & Stack
- Cloud: AWS (EKS, EC2, RDS/PostgreSQL, S3, IAM, VPC, CloudWatch, ALB/NLB)
- Orchestrator: Kubernetes (EKS), Helm (charts), Karpenter for node autoscaling
- IaC: Terraform (monorepo modules + environment stacks), Terragrunt for orchestration
- CI/CD: GitHub Actions (build/test), Argo CD (GitOps continuous delivery), Container registry (ECR)
- Observability: Prometheus, Grafana, Loki, Tempo, OpenTelemetry (OTel SDK + collectors)
- Alerting & Incident: PagerDuty, Slack on-call channels, status page via Statuspage
- Secrets & Auth: HashiCorp Vault, AWS Secrets Manager, Okta (SSO), SAML/OIDC integration
- Security & Compliance: SOC 2 Type II, CIS benchmarks, AWS IAM policy guardrails, image scanning (Trivy), SBOM generation
- Networking: Multi-AZ VPC, private subnets, NAT gateways, VPC endpoints, Service Mesh (Istio) pilot
- Data: PostgreSQL (RDS), Redis (ElastiCache), S3 data lake for batch jobs

Role Scope
- Own the build → deploy → operate platform path for 12+ microservices and 2 critical monoliths
- Define reliability standards (SLOs) and incident response guardrails across services
- Partner with backend leads on service maturity: logging, tracing, metrics, readiness/liveness, autoscaling policies
- Establish secure-by-default patterns: IAM boundaries, network segmentation, secrets handling
- Mentor 2–3 engineers and drive platform adoption through docs, templates, and enablement sessions

Success Profile (12 months)
- Measurable improvements in reliability (SLO adherence ≥ 99.95%)
- Deployment frequency increases while change failure rate decreases
- MTTR consistently < 30 minutes for P1 incidents
- Platform onboarding time for new services ≤ 2 days
- Documented platform architecture and runbooks widely adopted

Key Responsibilities
- Design and maintain Kubernetes deployment templates (Helm), GitOps workflows (Argo CD), and CI pipelines (GitHub Actions)
- Implement golden path service templates with OTel telemetry, health checks, and autoscaling defaults
- Own Terraform modules and environment stacks for multi-account AWS setup (dev/staging/prod)
- Define and enforce SLOs per service tier; build dashboards and alerts aligned to SLOs
- Lead incident response improvements and post-mortems with concrete prevention actions
- Drive cost optimization (rightsizing, autoscaling, storage lifecycle rules, Graviton adoption)
- Coach engineers and run platform office hours; write high-quality docs and RFCs

Constraints & Realities
- Budget-conscious: Prefer managed services where it reduces ops toil; avoid vendor lock-in where feasible
- Compliance: SOC 2 requires access controls, audit logs, change management, and documented runbooks
- On-call: Weekly rotation (primary + backup), reasonable load with escalation paths
- Remote culture: Clear written communication, design docs before implementation, async decision-making
- Security-first: No public S3 buckets, least-privilege IAM, image scanning required in CI

Example Outcomes (indicative)
- Reduce deployment lead time from 45 minutes to under 10 minutes per service via streamlined CI and pre-built templates
- Achieve 99.95% monthly uptime for tier-1 services; change failure rate under 15%
- Cut MTTR from 75 minutes to under 30 minutes through improved runbooks and alert routing
- Lower AWS compute costs by 15% without sacrificing performance (rightsizing, autoscaling, Graviton)
- Onboard 6 services to the paved road with standardized telemetry and rollout strategies (blue/green or canary)

Candidate Fit Signals
- Hands-on EKS/Kubernetes operations at scale (20+ services), Helm expertise, GitOps patterns with Argo CD
- Terraform modules for AWS networking (VPC, subnets, routing, IAM policies), multi-account setups
- Clear, practical incident management experience (PagerDuty, post-mortems with preventative actions)
- Strong documentation habits (RFCs, design docs, runbooks), mentorship track record
- Systems thinking: trade-offs, failure modes, and pragmatic, secure defaults

Timeline
- Target start within 6 weeks of offer acceptance
- Platform team aims to complete paved road v2 by end of Q3

Notes
- Service mesh (Istio) currently in pilot; adoption to be driven by clear benefits and measured outcomes
- Prefer standardization over proliferation; champion deprecation of bespoke scripts in favor of templates
- Build for self-service: product teams should provision pipelines and deploy safely without platform bottlenecks