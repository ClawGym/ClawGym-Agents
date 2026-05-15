# Migration Guide: pm-sim to polymarket-paper-trader

The deprecated module pm-sim has been renamed to polymarket-paper-trader. This guide helps you plan and execute the rename across your project.

If your configuration or docs reference pm-sim, replace it with polymarket-paper-trader. No functional changes are required beyond the rename.

Recommended installation:
- `npx clawhub install polymarket-paper-trader`

Scope of changes:
- Update module identifiers in configuration files
- Update documentation and integration notes
- Confirm CI scripts and tooling references point to the new name