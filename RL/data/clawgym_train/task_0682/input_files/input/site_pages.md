# Pre-Launch Website Content

We are preparing our product marketing content and need to verify every outbound link before launch. Below are sections that include call-to-action links, docs references, status test links, and community resources.

## Primary Calls to Action
- Visit our main site: https://example.com
- Fallback no-SSL demo: http://neverssl.com

## Documentation and References
- IANA Reserved Domains overview — [IANA Reserved](https://www.iana.org/domains/reserved)
- Wikipedia overview of web links — [Wikipedia](https://www.wikipedia.org)

## Status Test Links (for link health monitoring)
These are used by our CI checks and QA to simulate different HTTP responses:
- 200 OK example: https://httpstat.us/200
- 301 Redirect example: https://httpstat.us/301
- 302 Redirect example: https://httpstat.us/302
- 404 Not Found example: https://httpstat.us/404
- 418 Client Error example: https://httpstat.us/418
- 500 Internal Server Error example: https://httpstat.us/500
- 503 Service Unavailable example: https://httpstat.us/503

## Known Bad/DNS Failure Case
- Intentionally invalid domain for error handling tests: https://example.invalid

## Duplicate Mentions (intentional for dedupe validation)
- Another reference to 404: https://httpstat.us/404
- Another reference to main site: https://example.com

> Note: QA will extract and deduplicate all URLs from this file and the landing page before running the link audit.