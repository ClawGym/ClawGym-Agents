Goal
Design and run a workflow (input/workflow.json) using Workflow Orchestrator that:
- Uses only relative paths in commands.
- Avoids all forbidden shell metacharacters in commands: | ; & $ ( ) ` { } ! > < and no newlines.
- Implements helper scripts under output/scripts/ and references them from workflow commands.

Required steps (in order)
1) Generate a build ID and save it to a variable.
   - Implement a helper script that prints a non-empty ID to stdout (e.g., a timestamp or random string).
   - In the workflow, set save_output to capture this as build_id.

2) Write a report that includes the build ID and the message from input/vars.json.
   - Implement a helper script that writes exactly two lines to output/report.txt:
     - ID: <id>
     - Message: <message>
   - Pass the build ID via {build_id} and the message via {message}.
   - Use only relative paths.

3) Include a step that fails once, then succeeds on retry.
   - Implement a helper script that:
     - Fails with exit code 1 on the first invocation (e.g., by checking a state file under output/scripts/).
     - Succeeds (exit code 0) on the next run and prints ok to stdout.
   - In the workflow, set on_fail to retry and save_output (e.g., retry_output) so the final successful stdout contains ok.

4) Conditional step that only runs if the previous step’s saved output contains ok.
   - Use condition: ok in retry_output
   - Implement a helper script that writes output/conditional.txt containing ok if this step runs.

5) Write a final JSON summary.
   - Implement a helper script that writes output/summary.json with fields:
     - id: string equal to the build ID
     - message: string equal to the message from input/vars.json
     - conditional_written: boolean true iff output/conditional.txt exists
   - Use {build_id} and {message} substitutions.

Variable usage
- Load message and any target paths from input/vars.json into the workflow vars section.
- Use save_output to pass values between steps, e.g., {build_id} and {retry_output}.

Command safety
- Commands must NOT contain any of these characters after substitution: | ; & $ ( ) ` { } ! > < or newlines.
- Use simple argument passing (e.g., --id {build_id} --message {message}) without braces or JSON literals in the command itself.

Example command patterns (illustrative, adjust as needed)
- python3 output/scripts/gen_build_id.py
- python3 output/scripts/write_report.py --id {build_id} --message {message} --out output/report.txt
- python3 output/scripts/retry_once.py --state output/scripts/retry_state.txt
- python3 output/scripts/write_conditional.py --text {retry_output} --out output/conditional.txt
- python3 output/scripts/write_summary.py --id {build_id} --message {message} --out output/summary.json

Validation, dry run, and execution
- Validate the workflow and save console output to output/logs/validate.txt:
  python3 scripts/orchestrator.py validate --workflow input/workflow.json
- Dry run and save console output to output/logs/dry_run.txt:
  python3 scripts/orchestrator.py run --workflow input/workflow.json --dry-run
- Execute and save console output to output/logs/run.txt:
  python3 scripts/orchestrator.py run --workflow input/workflow.json

Artifacts to produce
- output/report.txt — Exactly:
  - Line 1: ID: <non-empty id>
  - Line 2: Message: <message from vars.json exactly>
- output/conditional.txt — Only if the conditional step ran; must contain ok.
- output/summary.json — Valid JSON with:
  - id: string equal to the ID from the report
  - message: string equal to the message from vars.json
  - conditional_written: true iff output/conditional.txt exists

Verification expectations
- output/logs/validate.txt contains a line starting with VALID:
- output/logs/dry_run.txt contains at least one line with [DRY]
- output/logs/run.txt contains WORKFLOW COMPLETE: and at least one line with RETRY
- Report and summary content must match requirements exactly