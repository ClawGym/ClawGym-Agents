OpenClaw Recovery Readiness Audit — Spec

Purpose
- Evaluate recovery readiness using only input/workspace.json and input/backups.json.
- Produce two outputs:
  1) output/report.json — machine-readable audit result
  2) output/summary.md — human-readable summary

Do not scan the filesystem; rely only on the provided input files.

Inputs
1) input/workspace.json
- Example structure:
  {
    "workspace_path": "input/workspace",
    "key_files": {
      "SOUL.md": true,
      "USER.md": false,
      "TOOLS.md": true,
      "MEMORY.md": true
    },
    "directories": {
      "memory": true
    },
    "runbook_signals": []
  }
- Interpretations:
  - key_files: Presence booleans for core operator files. The core operator files for scoring are: SOUL.md, USER.md, TOOLS.md. MEMORY.md is reported in evidence but is not a core-operator-file penalty trigger.
  - directories.memory: If absent or false, apply the memory-directory penalty.
  - runbook_signals: Array of present recovery/runbook/automation signals; empty means none found.

2) input/backups.json
- Example structure:
  {
    "current_time": "2026-04-01T12:00:00Z",
    "backup_roots": [
      {
        "root": "input/backups/primary",
        "exists": true,
        "artifacts": [
          { "name": "snapshot-1", "mtime": "2026-03-29T08:00:00Z", "size": 1234, "isDirectory": true }
        ]
      }
    ]
  }
- Interpretations:
  - Each backup root has a root path string, an exists boolean, and an artifacts array (may be empty).
  - artifacts[].mtime is an ISO8601 timestamp.
  - newest backup age (hours) = (current_time - max(artifacts.mtime among roots with exists=true and artifacts.length>0)) in hours, as a floating-point number rounded to one decimal place.

Scoring
- Start with score = 100.
- Apply penalties (subtract):
  - Missing core operator files (each of SOUL.md, USER.md, TOOLS.md that is false): -12 per missing file (HIGH severity, area: "workspace").
  - Memory directory missing (directories.memory is false or absent): -8 (MEDIUM severity, area: "workspace").
  - No candidate backup root found (backup_roots array empty OR no entry with exists=true): -35 (HIGH severity, area: "backup").
  - Backup root exists but has no artifacts (at least one exists=true, but across all exists=true roots the total artifacts count is 0): -25 (HIGH severity, area: "backup").
  - Backup freshness (computed newest backup age in hours):
    - > 168 hours (older than 7 days): -20 (HIGH severity, area: "backup-freshness").
    - > 48 hours (older than 48 hours) and <= 168 hours: -8 (MEDIUM severity, area: "backup-freshness").
  - No runbook signals (workspace.runbook_signals is empty): -10 (MEDIUM severity, area: "runbook").

Verdict
- FAIL if score < 60 OR any HIGH-severity finding exists.
- WARN if not FAIL and (score < 85 OR any MEDIUM-severity finding exists).
- PASS otherwise.

Required output fields
1) output/report.json
- JSON object with:
  - score: number (0–100 after penalties)
  - verdict: "PASS" | "WARN" | "FAIL"
  - summary: string (non-empty)
  - findings: array of objects with fields:
    - level: "HIGH" | "MEDIUM"
    - area: string (e.g., "workspace", "backup", "backup-freshness", "runbook")
    - issue: human-readable description
  - recommendations: array of strings (operator-focused remediation guidance)
  - drillPlan: array of strings, 5 or more steps; the first step must include the phrase "Restore the newest backup into a safe test path"
  - evidence: object containing:
    - keyFiles: map of the four key files (SOUL.md, USER.md, TOOLS.md, MEMORY.md) to booleans from workspace.json
    - backupRoots: array of objects:
      - root: string (from backups.json)
      - exists: boolean
      - count: number of artifacts for that root (0 if none or if exists=false)
    - newestBackupAgeHours: number, one decimal place
    - runbookSignals: array copied from workspace.json (may be empty)

2) output/summary.md
- Plain text lines:
  - A line with "Verdict: <verdict>"
  - A line with "Score: <number>"
  - At least three bullet points (- or *) listing key recommendations
  - A short 3–5 step drill plan; at least one step must mention restoring the newest backup into a safe test path

Evidence rules
- keyFiles are copied directly from workspace.json.key_files.
- backupRoots entries are derived from backups.json.backup_roots:
  - count equals artifacts.length when exists=true, else 0.
- newestBackupAgeHours is computed only if there is at least one artifacts entry under a root with exists=true; round to one decimal.
- runbookSignals is workspace.json.runbook_signals (an array).

Notes
- Use only the provided inputs; do not consult the real filesystem.
- Wording may vary, but required items, severities, and values must align with these rules.