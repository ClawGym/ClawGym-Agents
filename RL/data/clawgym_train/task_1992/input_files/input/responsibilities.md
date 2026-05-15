# Responsibilities – Michael Ortega (Staff ML Engineer, Applied AI)

## Ownership Areas
- Production ML services for risk and fraud detection (FraudShield v3, real-time anomaly detection “AnomalyGuard”)
- ModelOps / deployment pipeline:
  - CI/CD: GitHub Actions and Argo Workflows for model images and inference services
  - Infrastructure as Code for model infra (Terraform modules in `ml-infra/terraform`)
  - Canary + blue/green rollouts for model endpoints in AWS (EKS/ECS)
- Feature platform:
  - Feature Store migration to Feast (from custom Postgres-based store)
  - Feature validation jobs in Airflow (quality checks, missingness thresholds, drift monitors)
- Data and monitoring integrations:
  - Snowflake warehouses for feature computation and batch inference
  - Databricks clusters for training pipelines
  - Datadog monitors and dashboards for model latency and drift
- Security and compliance contributions:
  - PII handling guardrails in training pipelines (hashing, tokenization)
  - Contributor to internal “ML Privacy & Retention” SOP
- Documentation:
  - “ModelOps Runbook” (Confluence)
  - “AnomalyGuard Design Spec” (Confluence)
  - “Feature Store Migration Plan” (Confluence)
  - “FraudShield v3 Postmortems & Playbooks” (Confluence)

## On-Call Duties
- Weekly rotation for “ML-Platform” pager via PagerDuty (primary every 4 weeks; secondary every 4 weeks offset)
- 24/7 critical alerts for production model endpoints (latency, error rate, drift)
- Incident commander for Sev-2 incidents related to model degradation

## Critical Processes (runbooks Michael follows or owns)
- Model release process:
  1. Tag Docker image with semantic version
  2. Run integration tests and shadow traffic tests
  3. Approve rollout in ArgoCD; monitor Datadog SLO dashboards
  4. Rollback via `argo rollback <app>` if error budget breach > 5% over 30 minutes
- Access reviews for privileged roles (“ml-admin” in AWS, “SYSADMIN” in Snowflake, Databricks Workspace Admin) — quarterly attestations
- Secret rotation:
  - GitHub PATs for automation (scoped to `fraud-shield` and `ml-platform-tools`)
  - Databricks token rotation every 90 days
- Data privacy checks:
  - Verify datasets marked “Restricted” are anonymized during training
  - Ensure EU data residency configuration for logs and S3 buckets
- Vendor coordination:
  - AWS TAM for quota increases and EKS upgrades
  - Snowflake AE for warehouse sizing and credit limits
  - Datadog CSM for monitor tuning and billing alerts

## Known Risks if Not Handled During Offboarding
- Elevated privileges in AWS (“ml-admin” with AdministratorAccess) used for break-glass and some deploy operations
- Snowflake role “SYSADMIN” with broad grants
- Databricks “Workspace Admin” can create PATs and manage clusters
- GitHub “Repo Admin” on critical repos (e.g., `fraud-shield`, `ml-infra`)
- Active VPN (WireGuard) peer allowed into production bastion
- Company MacBook with local Docker images and cached credentials (AWS CLI profiles, Databricks CLI)
- YubiKey tied to SSO MFA; requires reassignment and seed removal