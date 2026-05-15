# Contributing

Thank you for improving the Tiny CLI To-Do Manager. This project values small, incremental, and safe changes.

Standards:
- Python 3.8+ compatible code
- snake_case function names
- Keep functions small and single-responsibility
- Use argparse for CLI parsing
- Print clear, user-friendly messages on success and error
- Exit with non-zero status codes on failure paths
- No external dependencies beyond the Python standard library

Non-destructive default:
- Do not delete or rename existing functions or commands
- Extend additively by introducing new functions and wiring them into the CLI
- Maintain backward compatibility for older data (e.g., handle missing fields with sensible defaults)

Data and persistence:
- Data is a JSON array of task objects: { "id": int, "title": str, "priority": str, "done": bool? }
- When adding persistence, use a safe/atomic write approach: write to a temporary file in the same directory and then replace the original

Tests:
- Use unittest
- Tests must not modify real project data files; prefer temporary files or in-memory data
- Keep tests deterministic and isolated

Zero placeholders:
- Do not include TODO or FIXME comments or strings in code or docs

Review checklist:
- Consistent naming and structure with existing code
- Helpful CLI UX: commands show useful help and informative messages
- No regressions to existing commands (list and filter must continue to work)
- No unnecessary side effects during operations that read data