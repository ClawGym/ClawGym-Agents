# TOOLS — Environment and Usage Notes

- When using the 'gog' CLI, include the --json flag to keep outputs parseable.
- Use 'tail -50' when reading session JSONL files to avoid excessive I/O and token usage.
- Default session files are stored under ~/.openclaw/agents/main/sessions/.
- Prefer explicit encodings when writing text files (UTF-8) to prevent cross-platform issues.