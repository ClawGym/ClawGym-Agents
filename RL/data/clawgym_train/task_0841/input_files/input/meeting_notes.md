Containerization notes — portfolio sync (2025-03-02)

NimbusPay (Series A)
- Status: migrating payments and risk services; ~60% of workloads in containers (partial)
- Orchestrator: Kubernetes on EKS
- Cloud: AWS
- Efficiency: infra costs down about 18% since migration; peak checkout latency improved ~35%
- Scalability: handled ~5x traffic during holiday via HPA; zero downtime

ShipRight (Seed)
- Status: moving from VMs; ~70% of services containerized (partial)
- Orchestrator: Docker Swarm
- Cloud: Azure
- Efficiency: cut infra spend ~22% q/q
- Scalability: promo spikes stabilized after adding autoscaling

QuantaLog (Series B)
- Status: fully containerized training pipelines and APIs (full)
- Orchestrator: GKE (Kubernetes)
- Cloud: GCP
- Efficiency: training jobs 40% faster; infra savings around 15%
- Scalability: HPA reduced queue times for model training

FieldStack (Seed)
- Status: pilot only; containerizing internal tooling (pilot)
- Orchestrator: none yet
- Cloud: On-prem first; exploring cloud burst
- Efficiency: deploys ~50% faster, no measured cost savings yet
- Scalability: n/a