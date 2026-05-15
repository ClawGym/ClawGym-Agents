Jordan Lee
Senior Software Engineer (Backend/Platform)
Email: jordan.lee@example.com | Location: Remote (USA) | GitHub: github.com/jordanlee

Summary
- Backend-focused engineer with 7+ years building reliable APIs, event-driven systems, and data pipelines across fintech, e-commerce, and healthcare.
- Deep experience with Go and Python, AWS (ECS, Lambda, SQS/SNS), Postgres, Redis, Kafka, and CI/CD (GitHub Actions).
- Strong in systems design, performance tuning, observability (Datadog), and mentoring.

Core Skills
- Languages: Go, Python, JavaScript/TypeScript
- APIs: REST, GraphQL (production experience; moderate depth)
- Cloud & Infra: AWS (ECS, Lambda, SQS, SNS, S3, RDS), Terraform, Docker, Kubernetes
- Data & Messaging: Postgres, Redis, Kafka, Airflow, Spark (EMR)
- DevOps & Quality: GitHub Actions, CircleCI, unit/integration testing, code reviews, SLOs
- Observability & Security: Datadog, OpenTelemetry basics, SOC 2 Type II readiness, HIPAA-compliant designs

Experience

FinchBank (Finch Financial), Senior Software Engineer
Aug 2023 – Present | Fintech payments and ledgering
- Led development of a high-throughput payments and ledger service in Go (gRPC + REST), Postgres, and Kafka; processed ~3M transactions/month with 99.99% service uptime.
- Introduced idempotent write patterns and outbox-based event delivery, reducing duplicate payment postings by 98%.
- Deployed on AWS ECS with autoscaling; used SQS/SNS for asynchronous workflows; Redis for hot-path caching and rate limiting.
- Implemented CI/CD pipelines in GitHub Actions; cut deploy time from 20 min to 7 min with canary strategy.
- Observability: standardized Datadog dashboards and SLOs; reduced MTTR by 35%.
- Security & Compliance: supported SOC 2 controls (logging, secrets rotation, least privilege IAM) and quarterly audits.
- Mentored 3 engineers; conducted design reviews and drove API standards.

NovaMart, Backend Engineer
May 2021 – Jul 2023 | E-commerce marketplace
- Built and maintained a GraphQL API (Node.js/NestJS) for catalog and order operations; added response caching and persisted queries.
- Implemented Python microservices for inventory sync and fulfillment; integrated with third-party logistics via REST and webhooks.
- AWS: SQS/SNS-driven order events, Lambda-based lightweight workers, Terraform for infra-as-code, Kubernetes (EKS) for core services.
- Postgres schema tuning (indexes, partitions) improved slow queries by 60%; Redis-based session and cache layer reduced API latencies by 30%.
- Partnered with product/design for A/B tests; contributed to code review guidelines and incident postmortems.

HealthLoop, Software Engineer
Sep 2018 – Apr 2021 | Digital health analytics
- Built HIPAA-aware data ingestion pipelines in Python (Airflow + Spark/EMR), normalizing EHR data for patient engagement analytics.
- Designed RESTful APIs and ETL workflows with auditing, encryption, and access controls; collaborated with compliance for privacy reviews.
- Improved data SLAs by 40% through backfill tooling and job orchestration guards.

Selected Projects
- Payments Ledger (Go, Postgres, Kafka, AWS ECS): Double-entry ledger, exactly-once semantics via outbox, schema versioning.
- Order Router (Python/Go): Rule-based router for marketplace orders; observability via Datadog and OpenTelemetry traces.
- HomeEnergy Hub (Side project): FastAPI services behind a GraphQL gateway; Terraform, GitHub Actions, Docker Compose.

Education & Certifications
- B.S. in Computer Science, University of Washington
- AWS Certified Solutions Architect – Associate (2025)

Notes relevant to job targeting
- Strong: Go/Python backend, REST APIs, AWS, Postgres, Redis, microservices, CI/CD, Datadog, Kafka, Terraform, SOC 2 exposure, mentorship.
- Partial: GraphQL (used in production at NovaMart, moderate depth; less deep on advanced federation).
- Domain familiarity: E-commerce (NovaMart), fintech (FinchBank), healthcare (HIPAA).