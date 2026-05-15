Cloud Cost Reduction Notes — Source of Truth

Goal
- Reduce monthly AWS infrastructure spend by ~30% while keeping deploy speed neutral or better.
- No change to release cadence. No increase in incident rate.

Headline numbers (use verbatim)
- Total monthly savings: $18,400 (37% reduction vs July baseline).
- Baseline monthly spend (July): $49,800.
- Post-optimization monthly spend (September): $31,400.

Measurement windows
- Baseline: July 1–31 (full month).
- After: September 1–30 (full month), all changes live by Aug 28.

Deploy performance (no slowdowns)
- CI/CD pipeline: containerized build → push → rollout to EKS.
- July deploy duration:
  - median: 8m 42s
  - p90: 10m 54s
  - p99: 14m 33s
- September deploy duration:
  - median: 8m 19s
  - p90: 10m 49s
  - p99: 14m 20s
- Conclusion: deploys did not slow down; small improvement at median and tail.

Environment (baseline)
- Kubernetes: EKS, 3 node groups (api, workers, batch).
- Instances (before):
  - api: m5.2xlarge (8 vCPU, 32 GiB), desired 8, max 12.
  - workers: m5.2xlarge, desired 10, max 40.
  - batch: m5.4xlarge, desired 2, max 10.
- Average cluster CPU utilization (July):
  - api: 38%
  - workers: 32%
  - batch: 29%
- Request/limit skew:
  - Many workloads requested 2 vCPU / 4 GiB but used ~0.8 vCPU / 1.6 GiB.
- Registry: Amazon ECR, default 200 images retained per repo.
- Builds: Docker BuildKit via GitHub Actions; remote cache stored in S3 with large layer churn.

What we changed (overview)
- We targeted compute first, then waste (images, cache), then scheduling polish.
- All changes were reversible and shipped behind feature flags where possible.

Change 1 — Compute Savings Plan
- Adopted 1-year, no-upfront Compute Savings Plan sized to steady-state baseline.
- Covered api and a portion of workers. Left burst capacity on-demand/spot.
- Saved: $7,900/month.

Change 2 — Spot for stateless workers
- Moved 30–50% of stateless worker capacity to Spot with interruption-friendly retry.
- Added queue visibility timeout and idempotent job handling.
- Saved: $3,200/month.
- No observed job failure rate increase (kept under 0.2%).

Change 3 — Right-size nodes and pod requests/limits
- Switched:
  - api: m5.2xlarge → c6i.xlarge
  - workers: m5.2xlarge → c6i.xlarge
  - batch: m5.4xlarge → c6i.2xlarge
- Reduced over-provisioning by tightening resources.requests and limits based on July 95th percentile.
- Saved: $4,100/month.
- Post-change average CPU:
  - api: 55–60%
  - workers: 58–62%
  - batch: 50–55%

Example (pod resources — target 95th percentile + headroom)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          resources:
            requests:
              cpu: "700m"
              memory: "1024Mi"
            limits:
              cpu: "1200m"
              memory: "1536Mi"
```

Change 4 — Autoscaling polish (schedule + consolidation)
- Enabled scheduled downscaling for business-hours traffic patterns.
- Turned on aggressive consolidation/scale-down for empty nodes.
- Saved: $1,800/month.
- No alert noise increase.

Example (Cluster Autoscaler excerpt)
```yaml
apiVersion: apps/v1
kind: ConfigMap
metadata:
  name: cluster-autoscaler
  namespace: kube-system
data:
  skip-nodes-with-local-storage: "false"
  scale-down-delay-after-add: "10m"
  scale-down-unneeded-time: "2m"
  scale-down-utilization-threshold: "0.40"
```

Change 5 — ECR lifecycle policy (images)
- Reduced retention from 200 to 15 images per repo, keep tagged releases.
- Saved: $700/month in ECR storage.
- No rollbacks blocked; releases always tagged and retained.

Example (bash — apply ECR lifecycle policy)
```bash
aws ecr put-lifecycle-policy \
  --repository-name api \
  --lifecycle-policy-text '{
    "rules": [
      {
        "rulePriority": 1,
        "description": "Keep last 15 images, expire others",
        "selection": {
          "tagStatus": "untagged",
          "countType": "imageCountMoreThan",
          "countNumber": 15
        },
        "action": { "type": "expire" }
      }
    ]
  }'
```

Change 6 — Build cache size and delta pushes
- Enabled BuildKit cache compression and reduced churn by pinning base images monthly.
- Switched pushes to use OCI diff-only where supported; trimmed layer size by ~18–25% on average.
- Saved: $700/month across S3 and egress.
- Build time impact: neutral; median builds improved slightly due to smaller pushes.

Example (GitHub Actions step snippet)
```yaml
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: ${{ env.IMAGE_TAG }}
    cache-from: type=gha
    cache-to: type=gha,mode=max,compression=zstd
    provenance: false
```

Reliability guardrails
- Spot: graceful termination hook + fast requeue; max in-flight reduction set to 10%.
- Autoscaling schedules kept minimum replicas for off-peak (api min 4).
- HPA cooldown doubled to avoid oscillation; rollout strategy unchanged.
- Incident count:
  - July: 0 Sev-1, 1 Sev-2 (unrelated to infra).
  - September: 0 Sev-1, 0 Sev-2.

Summary (verbatim figures to cite)
- “Total monthly savings: $18,400 (37% reduction vs July baseline).”
- “We went from $49,800 to $31,400 per month.”
- “Deploy duration stayed flat or improved: median 8m 42s → 8m 19s; p90 10m 54s → 10m 49s.”
- “Compute Savings Plan: $7,900/month saved.”
- “Spot for stateless workers: $3,200/month saved.”
- “Right-size nodes/requests: $4,100/month saved.”
- “Autoscaling polish: $1,800/month saved.”
- “ECR lifecycle: $700/month saved.”
- “Build cache compression/delta: $700/month saved.”

Attribution and method
- All dollar figures are AWS bill line-items aggregated by service and tagged environments (prod + shared).
- Deploy duration metrics are from CI telemetry (start of build → end of rollout).
- Utilization metrics from AWS and Prometheus, computed as 95th percentile per workload, then rounded to nearest 50m CPU for requests.