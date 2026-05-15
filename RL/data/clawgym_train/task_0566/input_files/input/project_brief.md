Supervised Agentic Loop — Local Evolve Run Brief

Overview
- Goal: Design and document a simulated, self-improving evolve loop that optimizes a single target file to minimize a numeric metric named val_bpb.
- Mode: Fully local and text-only. Do NOT execute any code; simulate outcomes consistently across artifacts.
- Skill context: Use the Brainstorm → Plan → Implement → Review → Verify → Evolve cycle with governance safeguards (git isolation, verification gates, reputation scoring).

Metric
- metric_command: python output/target/target.py
- metric_parser: val_bpb
- minimize: true (lower is better)
- Parser behavior: Extract a floating-point value from a line like “val_bpb: 0.987”.

Target
- Single target file to be evolved: output/target/target.py
- The final kept version must:
  1) Start with a single-line comment: final_version_commit: <hex> where <hex> is the commit of the best (lowest metric_value) keep row.
  2) Print a single metric line with exactly one print statement in the form: print("val_bpb:", <float>) where <float> equals the best kept metric_value.
  3) Contain a short, readable function or two (e.g., baseline_model(), improved_model()) and a main guard.
  4) Include the literal string in source code: metric_parser=val_bpb.

Loop Phases (brief)
- Brainstorm: Propose safe, minimal changes to the single target file to reduce val_bpb using hints from prior results and learnings.
- Plan: Create a concise task contract targeting only output/target/target.py, define acceptance criteria, and anticipate risk.
- Implement: Apply the modification to the target file only (respect read-only constraints and monitor for safety).
- Review: Check agent output aligns with the contract and intended change scope.
- Verify: Enforce four verification gates:
  1) file exists — output/target/target.py must exist
  2) syntax check — the Python file parses (e.g., via ast.parse) with no syntax errors
  3) tests pass — simulated test gate must be described as passing for kept changes
  4) lint clean — simulated lint gate must be described as clean for kept changes
- Evolve: Run metric_command (simulated) to extract val_bpb via metric_parser; keep change if strictly improves the best metric (minimization), otherwise rollback (discard).

Governance & Safety
- Git branch isolation: Run on a dedicated branch per evolve session; each iteration is committed separately. Non-improving iterations are rolled back automatically.
- Reputation scoring: Use EMA-style reputation in [0.0, 1.0]. Suspension threshold: ≤ 0.2 (auto-brake). Include reputation values in results.tsv per iteration to show trend.
- Auto-brake examples: suspension threshold reached, plateau detection (if applicable), max iterations, or manual interrupt (simulated).

Baseline
- Baseline is recorded as iteration 0 with status keep and hypothesis baseline. It seeds best_metric for comparison.
- If baseline “crashes” in a real run, the loop would hard-abort. In this simulated run, assume baseline is recorded successfully.

Deliverables (to write under output/)
1) output/plan.md
   - Describe exactly how to run the evolve loop locally against a single target file with:
     - metric_command: python output/target/target.py
     - metric_parser: val_bpb
     - minimize: true
   - Briefly explain each phase (Brainstorm → Plan → Implement → Review → Verify → Evolve).
   - Include the four verification gates by name (file exists, syntax check, tests pass, lint clean).
   - Mention git branch isolation and the reputation suspension threshold (≤ 0.2).
   - State how baseline is recorded and how keep/discard/rollback decisions are made.

2) output/results.tsv
   - Tab-separated with header exactly:
     iteration	commit	metric_value	status	hypothesis	duration_s	reputation
   - Include iteration 0 as baseline with status keep and hypothesis baseline.
   - Provide ≥ 5 additional iterations (≥ 6 total).
   - Only use statuses keep, discard, or crash.
   - For rows with status keep, metric_value must be strictly decreasing relative to the previous keep (minimization).
   - Include at least one discard or crash in iterations ≥ 1.
   - commit must match lowercase hex 7–40 chars.
   - duration_s is a positive integer; reputation is a float in [0.0, 1.0].

3) output/target/target.py
   - Must satisfy Target section above.
   - The printed float must equal the lowest metric_value across keep rows in output/results.tsv.
   - The first-line commit must match the best keep’s commit in output/results.tsv.
   - Include the literal: metric_parser=val_bpb.

4) output/.state/learnings/learned.md
   - ≥ 150 words, summarizing patterns observed.
   - Explicitly include the terms: pattern, verification gates, reputation, plateau, hallucination.
   - Propose at least two concrete rules for future brainstorms.

Additional Constraints
- Keep all artifacts internally consistent and text-only; no external dependencies, no actual execution.
- Simulate durations and reputation changes plausibly.
- Ensure strict chronological logic: a later keep must improve over the last keep.
- Make at least one iteration a discard or crash to demonstrate rollback behavior.
- Keep changes confined to a single file (output/target/target.py) per the evolve loop design.

Acceptance
- Submissions adhering to the above and consistent across all files are considered valid for evaluation.