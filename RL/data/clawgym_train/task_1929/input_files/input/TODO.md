# TODO

Last updated: 2026-04-17

## Current Tasks
- [ ] Curate PostgreSQL resources and export list (output/curated_list.txt)
  - Status: In progress
  - Owner: Ops/Tools
  - Notes: Ingest from input/resources.csv; include only Libraries, Tools, and Clients. Skip duplicates by name+url.
- [x] Implement duplication checks for ingest
  - Status: Done
  - Owner: Ops/Tools
  - Notes: Duplicate defined as same name and same URL.
- [ ] Draft context summary from TODO and roadmap
  - Status: Not started
  - Owner: Docs

## Blockers
- Awaiting final confirmation on whether "Clients" entries should be tagged separately in docs or merged under "Libraries". Proceeding with both included for now.
- No external dependencies expected.

## Recent Changes
- 2026-04-16: Added search verification step to ensure at least five entries were added.
- 2026-04-15: Decoupled export format from internal storage; export as plain text with date-prefixed lines.
- 2026-04-14: Standardized categories: Libraries, Tools, Clients, Extensions, Articles, Books.

## Notes
- Use only relative paths in all docs and commands.
- Data directory defaults to ~/.local/share/awesome-postgres/ unless overridden by AWESOME_POSTGRES_DIR.