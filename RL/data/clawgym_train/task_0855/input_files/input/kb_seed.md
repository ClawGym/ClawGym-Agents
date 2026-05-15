# Experience Summaries Seed

Use this seed to drive consistent triage and runbook entries. It summarizes categories, common symptoms, recommended actions, and a 5-step problem-solving workflow, plus a documentation template.

## Categories
- Installation: Failures during install/update of skills or tools (e.g., npm errors, missing binaries).
- Configuration: Missing or incorrect environment variables, tokens, or settings.
- Tool-Specific: Issues tied to a particular integration or extension (e.g., browser, gateway).

## Common Issues and Guidance

1) Windows global install EEXIST
- Symptoms: npm global install fails; messages like "EEXIST: file already exists" or rename errors in Roaming\npm.
- Probable Cause: Stale global install artifacts or permission conflicts block overwrite on Windows.
- Recommended Actions:
  1. Run: npm i -g <package> --force (e.g., npm i -g clawhub --force).
  2. If still failing, remove stale files: manually delete the conflicting folder under %APPDATA%\npm\<package>.
  3. Re-run installation with elevated shell if needed.
  4. Verify: clawhub --version.
- Prevention: Prefer clean uninstalls or use --force for global upgrades on Windows; avoid partially aborted installs.

2) Package installation 404 Not Found
- Symptoms: npm 404, package not in registry.
- Probable Cause: Wrong package name or skill available via ClawHub rather than npm.
- Recommended Actions:
  1. Verify spelling and search: clawhub search "<keyword>".
  2. Try npm search for alternates: npm search "<keyword>".
  3. Install via ClawHub if found: clawhub install "<skill-name>".
  4. Recheck docs for correct package name.
- Prevention: Always confirm package existence using search tools before installing.

3) Missing environment variable
- Symptoms: Tool exits with "ENV_VAR is not set" (e.g., TAVILY_API_KEY).
- Probable Cause: Required environment variables not configured in current shell/session.
- Recommended Actions:
  1. Set variable for current session (Windows CMD): set TAVILY_API_KEY=your-key
     (PowerShell): $env:TAVILY_API_KEY="your-key"
     (bash/zsh): export TAVILY_API_KEY=your-key
  2. Persist to shell profile if desired (e.g., ~/.bashrc, PowerShell profile).
  3. Verify: echo %TAVILY_API_KEY% (Windows) or echo $TAVILY_API_KEY (Unix).
  4. Re-run the tool and confirm success.
- Prevention: Document required variables in project onboarding; include a quick verification step.

4) Browser integration "tab not found"
- Symptoms: After a snapshot or click, follow-up actions fail with "tab not found".
- Probable Cause: Target tab was closed/detached or the extension lost attachment; gateway needs reseat.
- Recommended Actions:
  1. Restart OpenClaw Gateway (OpenClaw.app → Restart).
  2. Ensure Chrome extension badge is ON and attached to the active tab.
  3. Reattach: click extension → Attach Tab → verify badge ON.
  4. Repeat the action without closing or switching away from the tab; avoid long idle gaps.
- Prevention: Keep the tab open between operations; use the extension for one-time actions and reattach as needed.

## Problem-Solving Workflow (5 Steps)
1. Identify Category: Installation vs. Configuration vs. Tool-Specific.
2. Search the Knowledge Base: Match symptoms to entries and known fixes.
3. Apply Fixes Incrementally: Start with the simplest/common fix, then escalate.
4. Verify and Validate: Confirm the error is gone and the tool behaves as expected.
5. Document and Prevent: Record the resolution and add prevention notes for the team.

## Documentation Template
Use this template for each incident in the runbook:

Problem:
Scenario:
Solution:
Root Cause:
Prevention:
Platform Notes:

## Notes
- Use ClawHub CLI for skill discovery/installation when npm packages are unknown or unavailable.
- Standard environment variable verification commands:
  - Windows CMD: echo %VAR%
  - PowerShell: $env:VAR
  - Unix-like: echo $VAR
- For Windows-specific npm issues, --force often resolves global install conflicts.