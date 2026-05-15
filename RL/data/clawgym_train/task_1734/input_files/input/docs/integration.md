# Integration Notes

Existing integration scripts mention pm-sim in CLI commands and module references.

Update CI jobs to replace pm-sim with polymarket-paper-trader. For example:
- Install step: `npx clawhub install polymarket-paper-trader`
- Replace any imports or skill references that previously used the old name

Make sure no code changes beyond the rename are required.