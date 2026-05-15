# projctl — Project Scaffold and Settings Manager

This document specifies the functional requirements and behavior of the cross‑platform command-line tool “projctl”.

The CLI manages small project scaffolds and settings, supports pipeline-friendly I/O, and provides clear configuration precedence. It must be implemented using only relative paths at runtime and in docs.

---

## 1. General CLI Requirements

- Name: projctl
- Subcommands (minimum):
  - init
  - list
  - config get
  - config set
  - process
  - completion
- Standard options:
  - --help/-h (shows help at root and per subcommand)
  - --version/-v (prints semantic version)
- Exit codes:
  - 0 = success
  - 1 = runtime error (I/O failures, parse errors, etc.)
  - 2 = usage error (invalid flags/args, unknown subcommand, validation failure)
- Output conventions:
  - Respect pipelines (stdin/stdout). Do not emit extraneous logging unless requested.
  - Provide both human-friendly and machine-readable output modes where applicable:
    - --json for structured JSON
    - --quiet/-q for minimal output (typically IDs or names only)
- Cross-platform:
  - No hardcoded absolute paths.
  - Resolve user config using standard OS conventions (see Configuration).
- Completion:
  - Provide a “completion” command that prints a shell completion script for a requested shell.

---

## 2. Configuration

Configuration must follow a clear, documented precedence and be accessible to commands that need settings (e.g., defaults for init).

### 2.1 Precedence (highest to lowest)

1) CLI flags (e.g., --template)
2) Environment variables (prefixed with PROJCTL_, e.g., PROJCTL_TEMPLATE=web)
3) Project config file (in current working directory): ./projctl.json
4) User config file:
   - Linux: $XDG_CONFIG_HOME/projctl/config.json or ~/.config/projctl/config.json
   - macOS: ~/Library/Application Support/projctl/config.json
   - Windows: %APPDATA%\projctl\config.json
5) Built-in defaults from input/config_defaults.json

Notes:
- If a given key is not found at a higher level, fall back through the chain.
- Do not write to built-in defaults; defaults are read-only.
- For environment variables, convert names like PROJCTL_INIT_GIT to key init.git (nested keys may be expressed with underscores or dots, implementation choice allowed but document it).

### 2.2 Known keys

- template: default project template (string: minimal | web | api)
- editor: preferred editor command (string)
- color: enable colored output (boolean)
- telemetry: allow anonymous telemetry (boolean)
- init.git: initialize a git repository during init (boolean)
- projectDir: default directory for project creation (string path)

The default values are specified in input/config_defaults.json.

---

## 3. Commands

### 3.1 init

Initialize a new project scaffold.

Usage:
- projctl init <name> [options]

Arguments:
- <name> (required): lowercase alphanumeric and hyphens only (^[a-z0-9-]+$)

Options:
- -t, --template <template> (default from config): minimal | web | api
- --git/--no-git (default from config: init.git)
- -d, --dir <directory> (default from config: projectDir)
- -q, --quiet: minimal output (prints created path only on success)
- --json: print JSON object describing the scaffold result

Behavior:
- Validates name; on invalid name, print helpful message and exit 2.
- Simulate or create scaffold structure in the target directory (implementation may create directories and a minimal README if applicable).
- Respect config precedence for defaults.
- On success, print next steps; on --quiet, print only created directory path; on --json, output a JSON object like:
  { "name": "...", "template": "...", "directory": "...", "git": true }

Errors:
- Target directory not writable → exit 1 with message.
- Conflicting options or invalid template value → exit 2.

### 3.2 list

List projects from a JSON file or standard input.

Usage:
- projctl list [--file <path>] [--json] [-q|--quiet]

Input sources (in order):
1) If --file <path> is provided, read projects from that file.
2) Else if standard input is NOT a TTY, read from stdin.
3) Else: no input provided → usage error; print helpful message with example and exit 2.

Flags:
- --file <path>: path to a JSON file containing an array of project objects
- --json: output raw JSON array
- -q, --quiet: output only project names (one per line)

Input JSON format (array of objects):
[
  { "name": "web-app", "template": "web", "status": "active", "createdAt": "2026-01-02T10:03:00Z" },
  ...
]

Default behavior:
- Without --json or --quiet: print a simple aligned table with headers NAME, TEMPLATE, STATUS, CREATED.
- With --json: print JSON (no extra logs).
- With --quiet: print names only.

Errors:
- Failed to read/parse → exit 1, include filename if present.
- Empty input or wrong type → exit 2.

### 3.3 config

Manage configuration values.

Subcommands:
- projctl config get <key> [--json]
- projctl config set <key> <value> [--scope <scope>]

Options:
- --json (for get): prints JSON object { "key": "...", "value": "...", "source": "env|project|user|default|flag" }
- --scope user|project (for set): where to write the value; default user

Behavior:
- get: resolve using precedence; print value only by default (suitable for pipes). If key does not exist in any layer, exit 1 with message. If --json, include which layer the value came from.
- set: write value to the selected scope file (user or project). Create file/directories if needed. Print confirmation. For nested keys, allow dotted paths (e.g., init.git). Do not modify defaults or environment variables.

Errors:
- Invalid scope → exit 2.
- File write failures → exit 1.

### 3.4 process

Process project data, reading from file or stdin, and write the transformed result to stdout.

Usage:
- projctl process [--file <path>] [--uppercase] [--json]

Input:
- Same input source rules as list:
  - --file path wins
  - else if stdin provided, read stdin
  - else usage error (exit 2)

Behavior:
- Input is an array of project objects.
- For each project, add a computed field slug = normalized name (lowercase, non-alphanumeric replaced by hyphen, consecutive hyphens collapsed).
- If --uppercase is provided, names are uppercased in the output objects.
- Output:
  - If --json: print JSON array of transformed objects
  - Else: print one line per project, e.g., "<name> -> <slug>"

Errors:
- Read/parse errors → exit 1.
- Empty input → exit 2.

### 3.5 completion

Print a shell completion script to stdout.

Usage:
- projctl completion [bash|zsh|fish]

Behavior:
- Print a completion script appropriate for the CLI framework in use.
- If unsupported shell is requested, exit 2 with a message listing supported shells.

---

## 4. Input/Output Data Formats

### 4.1 Project JSON (input for list/process)

- name: string
- template: string (minimal|web|api or custom)
- status: string (active|archived|draft, etc.)
- createdAt: ISO 8601 timestamp

Sample file provided at input/sample_projects.json.

---

## 5. Examples

- List from file (quiet):
  projctl list --file input/sample_projects.json --quiet

- List from file (JSON):
  projctl list --file input/sample_projects.json --json

- List via stdin:
  cat input/sample_projects.json | projctl list

- Process via stdin with JSON output:
  cat input/sample_projects.json | projctl process --json

- Init with defaults resolved by precedence:
  projctl init my-app -t web --dir ./apps

- Config get with JSON:
  projctl config get template --json

- Config set to user scope:
  projctl config set editor "code" --scope user

- Completions:
  projctl completion bash > /tmp/projctl.bash
  source /tmp/projctl.bash

---

## 6. Testing Requirements

Provide basic string-based tests under output/projctl/tests/ that validate:
- Help text contains subcommand names and standard flags (--help, --version).
- Version flag prints a semantic version.
- The words init, list, config, process, completion, get, set, --json, and --quiet appear in source code or help text.

These can be implemented without network or external services.

---

## 7. Packaging and Entry Point

- Expose a console entry point named “projctl” via packaging metadata:
  - For Python: entry_points.console_scripts = ["projctl = <module>:app"]
  - For Node.js: package.json bin mapping: { "projctl": "./dist/cli.js" }
- Ensure source directory structure is clear (e.g., src/cli.py or src/cli.ts).
- No absolute, machine-specific paths in code or docs.

---

## 8. Error Messages

Provide helpful error messages that state:
- What failed
- Why it failed (if known)
- How to fix (e.g., “Provide --file or pipe JSON via stdin”)

Ensure non-zero exit codes on failure (1 or 2 as defined above).

---

## 9. Notes

- All config and examples should reference paths relative to the workspace (e.g., input/ and output/).
- The implementation should be pipeline-friendly: no colored output when stdout is not a TTY unless forced by config.

End of specification.