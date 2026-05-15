# Health Endpoints

Service exposes meaningful liveness and readiness checks:

- GET /health/liveness
  - Purpose: Process liveness
  - Checks: process uptime, event loop delay
  - Example response: `{"status":"ok","uptime": 12345}`

- GET /health/readiness
  - Purpose: Dependency readiness
  - Checks: DB connection, cache connectivity, message broker
  - Example response:
    ```
    {
      "status": "ok",
      "dependencies": {
        "postgres": "ok",
        "redis": "ok",
        "rabbitmq": "ok"
      }
    }
    ```

Security:
- Endpoints are unauthenticated but return no sensitive data
- Readiness includes dependency timeouts and failure reasons

Operational notes:
- Implemented in both API and web gateway
- Monitored via dashboards and used by Kubernetes probes