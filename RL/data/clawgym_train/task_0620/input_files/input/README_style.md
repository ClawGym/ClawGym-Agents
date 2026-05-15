# README Style Guide for projctl

Write a professional, user-focused README that is easy to scan and supports copy-pasteable examples. Follow this structure and content requirements.

Required sections (use these exact headings):
1. Introduction (first paragraph describes what projctl does)
2. Installation
3. Usage
4. Examples
5. Configuration
6. Exit codes
7. Contributing or Testing notes (brief)

Tone and style:
- Be concise and practical.
- Use fenced code blocks for commands.
- Prefer examples over long prose.
- Use relative paths only (e.g., input/sample_projects.json).
- Explicitly mention stdin, pipes, and redirection in relevant sections.

Include the following content elements:
- Show how to install the CLI and expose the projctl command (packaging metadata is provided in the project).
- Document subcommands: init, list, config (get/set), process, completion.
- Document standard flags: --help/-h and --version/-v.
- Demonstrate JSON output (--json) and quiet mode (-q/--quiet).
- Demonstrate pipeline usage:
  - Example: cat input/sample_projects.json | projctl list
  - Example: cat input/sample_projects.json | projctl process --json > output.json
- Provide an example that references input/sample_projects.json directly with --file.
- Configuration section must:
  - Explain precedence using the word “precedence”.
  - List config locations for project and user scope (mention XDG or OS-appropriate locations).
  - Show examples for config get/set, including --scope user|project.
  - Mention environment variables with PROJCTL_ prefix (e.g., PROJCTL_TEMPLATE).
- Exit codes section must explicitly list:
  - 0 success
  - 1 runtime error
  - 2 usage error

Additional notes:
- Mention that the tool avoids absolute, machine-specific paths and respects stdout for pipelines.
- If README includes a brief “Contributing” or “Testing” section, keep it short (a few bullet points or a paragraph).
- Avoid promises of features not implemented in this project.