# Luban CLI MLOps Guide

This guide defines the core entities, operations, and attributes to standardize the Luban CLI.

## Command Pattern
The CLI follows a consistent pattern:
- luban <entity> <action> [flags]

Entities:
- env — Experiment environments (dev workspaces)
- job — Training tasks (batch/asynchronous)
- svc — Online services (inference)

Output formats for list operations should support: table, json, yaml.

## Entities and Operations

### 1) Experiment Environment (env)
Purpose: Manage development and experimentation environments such as notebooks or dev containers.

Operations:
- list — List environments. Optional filters/format.
- create — Create a new environment with resource configuration.
- get — Retrieve details of a specific environment.
- update — Modify resource configuration or image of an environment.
- delete — Delete an environment.

Key attributes:
- name (string) — Unique environment name
- image (string) — Container image (e.g., pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime)
- cpu (int) — Requested CPU cores (e.g., 4)
- memory (string) — Requested memory (e.g., 16Gi)
- gpu (int) — Requested GPUs (e.g., 1)
- labels (map) — Optional key=value labels for filtering

Flag conventions for env:
- Use --name as the identifier for get/update/delete.
- Resource flags: --cpu, --memory, --gpu
- Image flag: --image
- list supports --label (key=value) and --output (table|json|yaml)

### 2) Training Task (job)
Purpose: Orchestrate asynchronous model training workloads.

Operations:
- list — List training jobs, optionally filtered by status.
- create — Submit a new training job.
- update — Update job metadata/settings (e.g., priority).
- delete — Delete a job.
- stop — Request a running job to stop.
- logs — Stream or fetch job logs.

Key attributes:
- id (string) — Job identifier (assigned by system; used for operations)
- name (string) — Human-friendly name
- script (string) — Entry script path (e.g., train.py)
- params (map) — Hyperparameters as key=value
- env (map) — Environment variables as key=value
- cpu (int), memory (string), gpu (int) — Resource requests
- output-path (string) — Output directory for artifacts
- status (enum) — queued|running|failed|completed

Flag conventions for job:
- Identifier: --id for get-like operations (update/delete/stop/logs)
- Creation: --script (required), optional --name, --params KEY=VAL, --env KEY=VAL
- Logs: support --follow, --tail N, --since DURATION, --timestamps

### 3) Online Service (svc)
Purpose: Deploy and manage inference services.

Operations:
- list — List services.
- create — Deploy a new service.
- update — Update service configuration (image, model path, port, replicas).
- delete — Delete a service.
- scale — Adjust replica count.
- status — Show current service status/health.

Key attributes:
- id (string) — Service identifier (often same as name; use --id for operations)
- name (string) — Required for creation
- model-path (string) — Path to model artifacts (e.g., ./models/v1 or s3://bucket/model)
- image (string) — Container image
- replicas (int) — Number of instances
- autoscale-min (int), autoscale-max (int) — Optional autoscaling bounds
- port (int) — Exposed service port

Flag conventions for svc:
- Identifier: --id for update/delete/scale/status
- Creation requires --name and --model-path
- Scale requires --id and --replicas
- list supports --label and --output (table|json|yaml)

## Flag Naming and Types
- Strings: --name, --image, --model-path, --script, --output, --since, --output-path
- Integers: --cpu, --gpu, --replicas, --port, --tail, --autoscale-min, --autoscale-max
- Booleans: --force, --follow, --timestamps, --verbose (store true if present)
- Enums (choices):
  - job --status: queued|running|failed|completed
  - job --priority: low|normal|high
  - list --output: table|json|yaml
- Key-Value repeats: --params KEY=VAL, --env KEY=VAL (can be repeated)

## Examples
- luban env create --name research-v1 --image pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime --cpu 8 --memory 32Gi --gpu 1
- luban job create --script train.py --name resnet50 --gpu 2 --params epochs=50 lr=0.01 --env WANDB_MODE=online
- luban job logs --id job_123 --follow --tail 200
- luban svc create --name classifier-v1 --model-path ./models/v1 --image registry.example.com/serving:1.2.0 --replicas 2 --port 8080
- luban svc scale --id classifier-v1 --replicas 5
- luban svc status --id classifier-v1 --verbose

## Notes
- Use --help on the root command, an entity, or an action to discover flags.
- Identifiers: env uses --name; job and svc operations use --id except creation, where svc uses --name and --model-path.

---

This guide is implementation-agnostic and describes the desired CLI behavior and flag semantics. See cli_requirements.yaml for the authoritative flag list and types to implement.