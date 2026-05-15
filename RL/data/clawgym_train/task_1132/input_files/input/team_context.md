Company: FleetDesk (SaaS for fleet operations and routing)
Stage: Growth (28 engineers; 3 SRE/Platform, 4 Data/ML, 5 Backend, 4 Frontend, 3 IT/Ops, 2 Security, 7 Mixed)
Monthly cloud spend (approx): ~USD 100–105k across AWS (~61k), Azure (~24k), and GCP (~18k)
Environments: prod (~80% of spend), staging (~12%), dev/sandboxes (~8%)

High-level architecture
- Core app (multitenant) on Kubernetes:
  - AWS EKS (prod, primary): API, worker services, cron jobs, and web frontends
  - Azure VMSS used for a small set of batch workers for an enterprise client
  - GCP GKE for analytics/data pipelines and experimentation
- Datastores:
  - AWS RDS PostgreSQL (prod Multi-AZ); one dev RDS also set to Multi-AZ
  - GCP Cloud SQL (Postgres) for events, with two read replicas that are lightly used
  - Azure SQL Database (Business Critical) for a legacy billing subsystem
  - DynamoDB (sessions, rate limits); Cosmos DB (event stream fanout)
- Storage:
  - S3 Standard for hot data, no lifecycle rules on several buckets
  - EBS volumes for EKS nodes; snapshots retained indefinitely without pruning
  - GCP PD-SSD with snapshots retained indefinitely
- Networking:
  - Notable cross-AZ and cross-zone traffic between app nodes and databases due to uneven node placements
  - NAT Gateways in each cloud handle substantial egress to public services (S3, third-party APIs, BigQuery)
- AI/ML:
  - Model training: 4 hours/day on GPUs; training nodes tend to be left “always on”
  - Inference: currently running on some GPU instance types though CPU latency is acceptable for 95th percentile
  - Azure OpenAI used for internal assistant; no response caching layer
- Observability:
  - Using Datadog Enterprise across all environments (but not in cost exports); also ingesting large volumes into cloud-native logs (CloudWatch, Azure Monitor, Cloud Logging)
  - Debug logs are enabled in production for multiple services; retention set between 90–180 days in some projects
  - Trace sampling set near 100%
- Security:
  - WAF enabled (AWS WAF, Cloud Armor); rules largely “default/managed” with minimal tuning
  - KMS used per-service including non-sensitive dev resources
  - Defender/GuardDuty enabled broadly
- Licensing:
  - Datadog Enterprise: 80 seats provisioned; 28 DAU, ~45 MAU; 22 seats inactive >60 days
  - GitHub Enterprise: 40 seats provisioned; 33 active
  - Windows Server/SQL Server: some Windows images used in staging and tools; SQL Server licenses on Azure SQL MI were removed last year (currently pay-as-you-go Azure SQL DB)
- Capacity strategy:
  - No AWS Savings Plans or RIs; no Azure Reserved VM Instances; no GCP CUDs
  - Little to no use of Spot/Preemptible for batch and nightly ETL
- Tagging:
  - Tagging exists but is inconsistent:
    - Many snapshots and some buckets have owner=unknown
    - Some compute nodes in dev/staging missing cost_center and owner
  - Current standard is app, team, owner, cost_center, environment
- Dev/Staging policy:
  - Staging mirrors prod autoscaling and HA policies; several dev resources run 24/7 with Multi-AZ enabled
- Compliance constraints:
  - No HIPAA/PCI; 90-day log retention is acceptable; 13-month retention not required
  - Production customer data residency is US-only; cross-region replication is not required for non-critical objects

Workload patterns and optimization signals
- Nightly batch windows (ETL and model training) run mainly 12:00–04:00 UTC; outside that, GPU/ETL instances mostly idle
- Read replicas in Cloud SQL and RDS show <5% read traffic relative to primary in off-peak hours
- EKS node CPU utilization averages ~32% during business hours, ~18% off-hours
- CDN is in use for static assets (CloudFront), but cache hit ratio is acceptable; no major CDN issues noted
- Object storage:
  - Buckets fleet-prod-data and dev-artifacts have no lifecycle rules; data older than 90 days accounts for ~38% of bytes
- Snapshots:
  - EBS and PD snapshots: many older than 6 months and not referenced by any current AMI/volume
- Networking:
  - NAT data processed is high relative to direct service endpoints; multiple services access S3/DynamoDB via NAT instead of gateway endpoints
- AI/ML:
  - Inference can run on CPU with minimal latency impact; training nodes can be auto-start/stop aligned with 4 hr/day window
- Observability:
  - Debug-level logs and 100% trace sampling driving high ingestion bills; metric cardinality has increased due to per-tenant custom labels

Team and ownership
- Platform: Emma (lead), Ben (tools), Li (infra)
- Data/ML: Steve (ETL), Maya (ML)
- DBA/Data: “DBA” shared role (rotating), supports RDS/Cloud SQL/Azure SQL
- Security: Eric
- Product/Frontend: Web team
- FinOps: No formal function; SREs handle cost items ad-hoc

Assumptions for analysis (acceptable adjustments)
- Rightsizing: Target average node utilization to 55–65% for container nodes
- Storage lifecycle: Move objects >90 days to infrequent access or archive tiers where access patterns permit
- Snapshot hygiene: Retain last 30–45 days for non-critical envs, 90 days for prod; remove orphans
- NAT optimization: Use VPC/VNet endpoints and private links for S3, DynamoDB, and other core services
- RIs/Savings Plans/CUDs: Commit 70–80% of steady-state compute for 1-year term
- Logging/Tracing: Reduce debug logs in prod; apply sampling (10–20%) and lower retention (30–60 days) unless required
- AI/ML: Schedule GPU training to 4 hr/day; migrate inference from GPU to CPU autoscaling
- Dev/Staging: Disable Multi-AZ for dev; scale staging to 30–50% of prod and shut down nights/weekends where possible

Known constraints
- No hard compliance retention requirements beyond 90 days for logs
- Customer SLAs permit 99.9% uptime; Multi-AZ not required for non-prod
- No strict forensics requirement for all logs; sampled traces acceptable for investigations