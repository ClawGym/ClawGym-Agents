# Architecture Overview

NebulaDrive consists of stateless API services, a metadata database, and object storage for file blobs. Clients maintain local state and synchronize via streaming or batch modes.

## Components
- Gateway API: Handles REST and WebSocket connections.
- Metadata Service: Manages file trees, permissions, and version metadata.
- Sync Orchestrator: Schedules and coordinates streaming/batch operations.
- Worker Fleet: Processes uploads, deduplication, and background tasks.
- Object Storage: Stores encrypted file chunks and versions.

## Data Flow
1. Client encrypts content and computes chunk boundaries.
2. Encrypted chunks are uploaded to object storage.
3. Metadata service records chunk references and version lineage.

## Reliability
- Multi-AZ deployments by default.
- Back-pressure and circuit breakers in client libraries.
- Graceful degradation for thumbnailing and preview generation.

## Observability
- Structured logging, OpenTelemetry traces, and metrics exported to Prometheus.
- Dashboards for latency, error rates, and resource utilization.