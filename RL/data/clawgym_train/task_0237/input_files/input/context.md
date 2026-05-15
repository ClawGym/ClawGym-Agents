Project: Fixture Aggregator microservice.
- Purpose: Pull match fixtures from 3–5 provider APIs every minute, deduplicate, and expose read APIs (REST + lightweight WebSocket) for clients.
- Traffic: ~100 requests/sec; p95 latency target <50 ms for cached reads and <200 ms for fresh fetches.
- Team: 3 engineers; comfortable with Python and Go; OK with Node/Java if compelling.
- Deployment: Ubuntu 22.04 on containerized VMs; prefer minimal ops overhead.
- Preferences: Built-in or first-class async/concurrency model and schema validation to maintain reliability.