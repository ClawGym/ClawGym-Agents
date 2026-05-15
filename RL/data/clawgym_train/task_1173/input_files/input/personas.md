# Personas for Social Scraping Implementation

- Primary Persona: Data Engineer (Acme)
  - Goals: Build compliant scrapers, deliver reliable datasets to downstream analytics, minimize operational toil.
  - Needs: Clear quickstart, patterns for retry/backoff and robots handling, actionable debugging and performance tips, security controls aligned to policy.
  - Tools: Python, Bash, Airflow, internal logging/metrics stack.

- Secondary Persona: Compliance Officer
  - Goals: Ensure activities honor robots.txt and terms, prevent PII over-collection, maintain auditability and approvals.
  - Needs: Transparent sources matrix, explicit security section mapping to policy keys (respect_robots_txt, user_agent, rate_limit_rps, prohibited_actions, data_retention_days, pii_handling).

- Secondary Persona: Security Engineer
  - Goals: Identify and mitigate threats across STRIDE, validate access controls and storage encryption, ensure incident response hooks.
  - Needs: Threat model (STRIDE + DREAD), concrete mitigations, logging without secrets, least-privilege access patterns.

- Tertiary Persona: Product Analyst
  - Goals: Consume processed, de-identified datasets; understand data freshness and limitations.
  - Needs: References to allowed sources, retention windows, and data quality notes.

Tone guidance:
- Write in clear, actionable English.
- Prefer checklists, step-by-step flows, and tables where helpful.
- Keep offline and self-contained; do not assume external network access from the reader’s environment.
- Align every recommendation to company policy where relevant.