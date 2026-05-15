# Popup CRO Toolkit — Requirements

Goal
- Build a reusable toolkit that helps marketers and developers plan, design, implement, and optimize website popups/modals/overlays to increase conversion rates while maintaining a positive user experience and compliance with policies.

Scope
- Toolkit should cover strategy, copywriting templates, trigger/targeting rules, mobile adaptations, compliance guidance, and A/B test planning. It should output human-readable artifacts (Markdown) and machine-readable configs (JSON) for implementation teams.

Core Deliverables
1) Popup Strategy Map
- Describe for each recommended popup: type (email capture, lead magnet, discount, exit intent, announcement, slide-in), trigger (time delay, scroll depth, exit intent, click-triggered, page count, behavior-based), audience (new vs returning, traffic source, page type), frequency cap rules, and conflict resolution if multiple popups could fire.
- Output: strategy_map.md (human-readable) and strategy_map.json (structured).

2) Complete Popup Copy Sets
- For each popup, provide headline, subhead, CTA button text, decline text, and a 1-line preview/teaser.
- Voice and tone should be professional and concise; avoid manipulative decline copy.
- Output: copy_sets.md and copy_sets.json.

3) Trigger Timing Optimization
- Provide recommended defaults and rationale for desktop vs mobile (e.g., 30–60s delay, 25–50% scroll, mobile back-button as exit intent proxy).
- Provide an A/B test matrix with at least 6 test ideas across timing, format, messaging, and targeting.
- Output: triggers_and_tests.md.

4) Audience Targeting Rules
- Recommend targeting logic by page type (blog vs product vs pricing), traffic source alignment (paid vs organic), and user status (new vs returning, converted vs not).
- Include exclusion rules (checkout, already-converted, recently dismissed).
- Output: targeting_rules.md and targeting_rules.json.

5) Mobile Adaptation Notes
- Specify mobile-friendly formats (bottom slide-ups, smaller modals), touch targets, dismissal behavior, and avoidance of intrusive interstitials that harm SEO.
- Provide device-specific trigger substitutions (e.g., exit intent alternatives).
- Output: mobile_adaptations.md.

6) Compliance Checklist
- Include GDPR consent mechanics (no pre-checked boxes, privacy link), accessibility requirements (keyboard navigation, focus trap, ARIA labels, color contrast), and Google mobile interstitial policy guidance.
- Output: compliance_checklist.md.

7) Measurement & Data Schema
- Define key metrics (impressions, conversions, close rate, engagement rate, time to close) and events to track (view, focus, submit, close, outside click, Esc).
- Provide a minimal JSON schema for logging popup interactions, including popup_id, variant_id, timestamp, device, page_url, event_type, and metadata.
- Output: analytics_and_schema.md and events_schema.json.

8) Implementation Handoff
- Provide a consolidated README explaining how to use the outputs, how to prioritize tests, and how to roll out safely.
- Include an example configuration bundle for a sample website section (e.g., blog) with two popups and conflict rules.
- Output: README_toolkit.md and example_bundle.json.

Non-Goals
- Do not include any proprietary platform integrations (e.g., specific CMS/plugin code). Focus on platform-agnostic outputs and guidance.
- Do not ship production code; provide specifications, templates, and structured configs only.

Constraints
- Ensure the plan starts in a Plan mode (no code) and includes a mandatory plan revision cycle based on self-critique.
- Build requests should reference implementing the approved plan into the specified artifact files only (Markdown/JSON).
- The plan must include at least 6 concrete steps and cover all core deliverables listed above.

Quality Criteria
- Clarity: Each artifact must be self-explanatory and internally consistent.
- Completeness: All deliverables must be covered with examples and testable hypotheses.
- Compliance: Explicitly address GDPR, accessibility, and Google’s mobile interstitials policies.
- Practicality: Recommendations should be immediately usable by marketers with minimal developer support.