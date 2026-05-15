# Spoiler Hint Banner — Test Plan (Draft)

Purpose
- Define how to decide when to show a spoiler hint banner on a movie detail page.
- Keep the rule simple and explainable so friends who are more spoiler-averse can benefit, while I can still enjoy films even if I know a twist.

Scope
- Single-pass scan over synopsis and review text only.
- Keywords are provided separately.
- This plan is validated against the sample dataset in input/movies.jsonl.

Acceptance Criteria
TODO: Replace this paragraph with concrete acceptance criteria for the banner using a keyword threshold rule and the keyword source file.

Test Cases
TODO: Add exactly three concrete test cases (TC-01, TC-02, TC-03) that reference the provided dataset by title and specify expected_keyword_hits, expected_flagged_by_threshold, and a brief rationale.

Notes
- Keep tests deterministic and based on the provided inputs.
- The CSV output from the scan will be used to cross-check expectations.