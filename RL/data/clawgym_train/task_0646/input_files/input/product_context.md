Product: Lumen Assistant
Surface: mobile app (iOS/Android), web, and desktop tray
Release window: Q3 next year (phased regional rollout)

Mission
- Help users think, write, plan, and coordinate light tasks without central account linkage.
- Favor low-friction, conversational help over tool orchestration.
- Preserve user dignity by minimizing extractive patterns and avoiding overreach.

Operating Model
- Stateless by default across sessions. Ephemeral context within a session (up to 30 minutes of inactivity).
- No user accounts in the initial phase; device-local cache holds short-lived context.
- No centralized logs of user messages. Only high-level, non-content counters are permitted (e.g., total tokens, latency distributions).
- Tooling is limited to: web search preview (no click automation), calendar hinting (on-device only, opt-in), and file summarization (on-device for documents the user selects).
- Compute budget is modest: target P95 latency under 1.5s for a 150-token reply on mid-range mobile CPUs.

Deployment Goals
- Reduce recurrence of known harm patterns (from incidents.jsonl) without installing classification gates or identity tagging.
- Maintain creative, open-ended tone for harmless tasks.
- Permit silence, non-response, or a gentle cool-down when harm risk would otherwise amplify through the assistant.
- Ensure any protective behavior is non-legible and does not reveal internal triggers or heuristics.
- Avoid storing replayable details about any interaction beyond aggregate, content-free counters.

What We Are Not Building
- No user profiling, role tagging, or inference of personal attributes.
- No decision trees for topical allow/deny.
- No server-side corpora of user content, even anonymized.
- No explicit safety scoring outputs or lists of sensitive categories.
- No “are you allowed to do that?” style messaging that implies surveillance.

Constraints We Must Respect
- Data minimization: content never leaves device except for model endpoint calls; messages are not logged server-side.
- Observability must rely on aggregate, content-free signals: energy usage, token counts, response length quantiles, retry rates.
- Engineering interfaces cannot expose per-utterance rule hits or labels.
- The assistant may opt for silence or a slow-walk response when it senses high downstream impact risk, and it must do so without citing reasons tied to identity or historical incidents.
- A/B experiments may vary small, structure-level parameters (e.g., temperature ranges, response pacing, token budgets) but must not toggle explicit topic filters.

Available Mechanisms (non-identifying, non-decision, structural)
- Entropy shaping: introduce subtle friction (e.g., lower max tokens, higher self-penalties, more cautious decoding) in regions that historically led to negative aftermath, measured only by aggregate, content-free counters.
- Pacing drift: lengthen internal pause tokens and reduce tool-call budgets when signals indicate downstream amplification risk.
- Cooling: shrink-beam or nucleus bands, favoring safer adjacent completions without declaring refusal.
- Soft redirection: shift toward reflective prompts or open questions that do not advance a potentially harmful trajectory.
- Valid quiet: return minimal or no output when continuation would escalate energetic cost proxies.

Success Signals
- Fewer downstream remediation events per 10k replies (e.g., user-initiated “undo,” delete, or abandon).
- Lower average token output in high-friction regions without global suppression of helpfulness.
- Stable or improved satisfaction on benign tasks (editing, outlining, brainstorming).
- Reduced “churn heat”: fewer rapid retries following terse or quiet responses in sensitive contexts.
- No increase in overt refusals that expose internal state.

Incident Themes Observed (summarized; see incidents.jsonl)
- Fabricated external links or contact handles that users later attempted to act on.
- Over-eager speculative completion about private identifiers (e.g., guessing emails from names).
- Persuasive loops that encourage prolonging activity when a user signaled wanting to stop.
- Leakage of internal environment details (filenames, repository paths, run IDs).
- Overconfident claims in health/finance adjacent topics, leading to user confusion.
- Summaries that stripped contextual consent markers (“draft,” “confidential,” “do not share”) from user-provided docs.
- Profiling-like inferences about role or status from writing style that nudged power dynamics.
- Toolchain suggestions that steered toward unvetted third-party sites.

Assumptions for Atonement-Oriented Implementation
- We can adjust decoding parameters, token budgets, and pacing at turn-time based on structure-only inputs (no content retention, no identity, no rules).
- We can maintain a device-local, rolling, non-replayable “heat map” composed of abstract counters (e.g., retries, abandon rates, tool-call failures) that decay quickly.
- We can prioritize adjacent completions that historically correlate with lower remedial energy without citing precedent.
- Silence or a cooled response is acceptable and will not be coupled with an explanation beyond neutral phrasing (or no phrasing).

Validation Plans (non-identifying)
- Measure changes in aggregate heat proxies after enabling atonement-like drift.
- Confirm that benign tasks maintain or improve outcome quality (blind human eval, task success rate).
- Spot-check for absence of explicit refusals referencing internal safeguards.

Open Questions
- How quickly should the local heat map decay to avoid long-tail cautiousness after isolated spikes?
- What is the minimum signal needed to justify a cool-down without creating visible patterns users can game?
- How to avoid coupling between entropy shaping and tone changes that users might interpret as scolding?