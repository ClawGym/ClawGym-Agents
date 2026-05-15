Team snapshot
- Team: Platform Acceleration Team (14 engineers; 3 new hires; mix of backend and platform)
- Codebase: Monorepo with microservices in Go and Node.js; internal CLIs in Bash/Python
- Hosting: Staging in AWS; production managed by a central SRE group; we aim to stay cloud-agnostic in training
- VCS: GitHub (trunk-based with protected main; feature branches; PR reviews required)
- CI/CD: GitHub Actions (runners are Ubuntu-based); we want faster pipelines and clearer stages
- IaC: Terraform for infrastructure modules (VPC, RDS/Postgres, S3-like object storage); Ansible for config and bootstrap
- Containers: Docker and Docker Compose locally; explicitly not using cluster orchestration in this onboarding
- Observability: Prometheus + Grafana + Loki stack under evaluation for services; basic alerts via Alertmanager
- Security: Baseline scanners in CI (Trivy for images, Gitleaks for secrets, hadolint for Dockerfiles)
- Backups/DR: Postgres backups exist, but runbooks are incomplete; want restic-based demos to standardize knowledge transfer

Training goals and constraints
- Time: 90 minutes per day for 10 consecutive workdays
- Hands-on: Required daily; command-first, reproducible labs; everything runnable on Ubuntu 22.04 laptops
- Admin rights: Limited; prefer containerized labs and local services; avoid global system changes
- Tooling preferences:
  - CI/CD: Use GitHub Actions (avoid external CI)
  - IaC: Terraform + Ansible (prefer modules and idempotent playbooks)
  - Containers: Use Docker and Docker Compose; keep scope to local dev and CI workflows
  - Observability: Prometheus, Grafana, Loki (Loki optional if time-constrained)
  - Cloud: Keep vendor-neutral; if needed, use LocalStack to emulate AWS and MinIO for object storage
- Exclusions: Avoid Kubernetes and other cluster orchestration; avoid Jenkins; avoid Chef; no GUI-heavy tools
- Outcomes: Each day should produce a small artifact (e.g., a workflow file, Terraform module skeleton, Ansible role, Dockerfile, dashboard JSON), committed in a dedicated onboarding branch. End of Day 10: a minimal, integrated path from commit to container to metrics with basic SLOs.

Context-specific priorities
- Standardize Git hygiene (commit messages, branching, PR templates) and trunk-based flow
- Improve CI speed by caching modules and dependencies; add quality gates (lint, test, scan)
- Establish a minimal IaC pattern (Terraform) and config management baseline (Ansible)
- Build confidence with containers using Dockerfiles and Compose for local integration testing
- Introduce observability fundamentals with a runnable local stack and a simple dashboard
- Cover security scanning and secret handling basics that fit GitHub Actions
- Ensure backups and restore drills are demonstrated end-to-end locally with restic
- Introduce cloud abstractions without vendor lock-in (LocalStack where helpful)
- Anchor reliability with basic SRE concepts: SLI/SLO, error budgets, incident hygiene

Environment assumptions for labs
- Ubuntu 22.04, Bash available, Git installed
- Docker and Docker Compose pre-installed or runnable via rootless setup
- Terraform >= 1.5 and Ansible >= 2.14 available in containers or via devcontainers
- Internet access for pulling images and modules
- Monorepo clone available; a scratch folder for onboarding artifacts is acceptable
- The 90Daysofdevops CLI wrapper is available as a simple shell script for help/info/status reference; we will embed its help/outputs in the plan’s Tooling reference

Success criteria
- By Day 10, new team members can:
  - Commit code with standardized practices (Git)
  - Run and interpret a CI pipeline in GitHub Actions with lint/test/scan stages (CI/CD)
  - Define a small Terraform configuration and run plan/apply safely against a localstack target (Infrastructure as Code + Cloud)
  - Use Ansible to configure a containerized service locally (Automation)
  - Containerize a microservice and run it via Docker Compose with a Postgres dependency (Containers)
  - Expose basic service metrics and view them in Grafana (Observability)
  - Run a restic backup and perform a small restore test (Backups)
  - Explain SLI/SLO basics and add a lightweight reliability check (SRE)
  - Address basic security hygiene with CI scanners and secret handling (Security)

Notes to the curriculum author
- Please compress the 90-day DevOps learning map thoughtfully into 10 days using the topics above; avoid excluded tools completely in all outputs.
- Keep daily labs scoped to what can be achieved in 90 minutes, with commands that work on Ubuntu and favor containerized workflows.
- Include a “Tooling reference” section that embeds the 90Daysofdevops CLI help/info/status outputs verbatim for quick discovery.