# User Preferences and Constraints

Device: Raspberry Pi 4 Model B (4GB RAM), 32GB microSD. Running OpenClaw in a constrained environment.

Cleanup constraints:
- Avoid clearing the pip cache. Do not run any pip cache purge commands.
- Always perform a dry run first and show what would be removed before executing any deletions.
- Do not terminate SSH sessions or the OpenClaw gateway process.
- Do not kill my interactive Chromium browser window; closing headless/test browser instances is fine.
- Ask for confirmation before any aggressive cleanup steps.
- Keep browser logins and profiles intact unless they are clearly test-only or automation caches.

Path and instruction constraints:
- In any cleanup plan or instructions, reference only relative workspace paths (e.g., input/ and output/). Do not use absolute OS paths.
- Prefer listing actions against workspace-managed caches and session folders when possible.

Operational preferences:
- One browser at a time; close the browser after use.
- Prefer web_fetch over full browser automation when feasible.
- Limit concurrent subagents to 2 on this device.
- Please suggest a low-spec-friendly configuration including free/lightweight models and turning thinking off by default.