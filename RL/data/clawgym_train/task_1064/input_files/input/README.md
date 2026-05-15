# Tiny CLI To-Do Manager

A minimal command-line to-do manager that reads tasks from a JSON file and provides simple listings and filtering.

Current features:
- list: print all tasks
- filter: print tasks filtered by priority (low, medium, high)

Data model (JSON array of objects):
- id (int): unique identifier for the task
- title (string): short description
- priority (string): one of "low", "medium", "high"
- done (boolean): optional; may be absent in older data (treated as pending)

Conventions:
- Language: Python 3.x
- Style: snake_case for function names, small pure functions, clear print messages
- CLI: argparse with subcommands
- Data path: defaults to tasks.json located alongside the script; can be overridden with --file
- Error handling: fail with clear, actionable messages; return non-zero exit codes on errors

Usage:
- List all tasks
  python app.py list
- Filter by priority
  python app.py filter --priority high
- Specify a custom data file
  python app.py list --file /path/to/tasks.json

Non-destructive change policy:
- Preserve existing functions and behavior
- Add new functions and commands rather than renaming or deleting
- Maintain backward compatibility for existing data (handle missing fields sensibly)

Testing:
- Use Python’s built-in unittest
- Keep tests self-contained; do not modify real data files during tests

Zero placeholders:
- No TODO or FIXME strings anywhere

Directory layout:
- app.py — CLI entry point and command handlers
- tasks.json — sample task data