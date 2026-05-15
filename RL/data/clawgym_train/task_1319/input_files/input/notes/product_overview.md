# NebulaDrive Product Overview

NebulaDrive is a secure, cross-platform file sync and sharing service designed for enterprise collaboration with zero-knowledge encryption and high availability.

## Key Capabilities
- Cross-device sync with automatic conflict resolution.
- End-to-end encryption with client-managed keys.
- Scalable architecture supporting millions of files and users.
- Robust audit logs and policy enforcement.

## Sync Modes

Streaming Sync applies changes in near real-time using a persistent WebSocket connection.
Batch Sync groups changes into 5-minute windows and applies them on schedule.

### When to use each mode
- Choose Streaming Sync for collaborative editing and low-latency updates.
- Choose Batch Sync to reduce network chatter during predictable update windows.

## Platforms
NebulaDrive supports Windows, macOS, Linux, iOS, and Android clients, plus a web dashboard for administration.

## Performance Notes
- Streaming reduces perceived latency but increases idle connection overhead.
- Batch reduces connection overhead but may delay eventual consistency.