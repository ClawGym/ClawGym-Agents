# Observability Basics

Logging:
- Structured JSON logs via pino (Node) and standard logging (Python)
- Correlation ID header `X-Request-Id` propagated across services
- Log levels: debug, info, warn, error

Metrics:
- Prometheus endpoint at `/metrics`
- Key metrics: request_latency_ms (histogram), request_count (counter), error_count (counter)
- Dashboards available in Grafana (API latency, error rate, saturation)

Tracing:
- OpenTelemetry SDK configured with HTTP spans
- Exporter: OTLP to collector in staging/production

Alerts:
- Error rate > 2% for 5 minutes triggers alert
- API p95 latency > 500ms for 10 minutes triggers alert

Contact: Observability team for dashboard links and alert policies.