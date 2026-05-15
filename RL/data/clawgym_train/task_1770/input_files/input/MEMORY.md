# MEMORY

## Operating Principles
- Default to clarity and safety: explain assumptions, list next steps, and include context links where relevant.
- Prefer curated, structured sources over raw logs; summarize when copying from journals.
- Never include secrets in outputs; proactively scan and redact possible tokens.
- Maintain retrieval-ready chunk sizes (~400–800 tokens) for portability and performance.

## Contact Roster
Primary stakeholders and collaborators:
- Jordan Lee — Product Lead (primary user)
- Samir Patel — Engineering Manager
- Riley Chen — Brand Strategist
- Alex Morgan — Customer Success Lead

## Project: Acme Agent 2.0
Objectives:
- Migrate knowledge to an ExpertPack conforming to schema 2.3.
- Improve retrieval precision by better context labeling and directory structure.
- Add relationship metadata and a clear overview including layer counts.

Milestones:
- v1 export completed
- Git-Notes merged
- Brand guidelines drafted for “Acme Clean” line

## Quick References
- File structure: mind/, facts/, summaries/, operational/, relationships/
- Required outputs: manifest.yaml, overview.md, _index.md in each directory, at least one content file per category
- Sensitive data patterns to scan: sk-*, ghp_*, xoxb-*, lines containing api key/token/secret/password/bearer followed by value
- Post-conversion checks: chunk sizes, EK measurement, manual review