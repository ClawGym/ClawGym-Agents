Audience: Platform engineers responsible for Kubernetes, GitOps, and compliance.

Goal: Draft a polished technical guide on rolling out configuration drift detection using GitOps and policy-as-code. Make it practical and operator-friendly, with examples the reader can copy into a repo or CI step.

Structure (must be exact):
- H1 title (your choice)
- H2: “## The scene”
- H2: “## Why drift hides”
- H2: “## Implement the guardrails”
- H2: “## Rollout plan”
- H2: “## Takeaways”

Key requirements:
- Open with something concrete. The first non-empty paragraph must contain a specific number from input/research.json OR start with a fenced code block.
- Include at least two fenced code blocks with practical examples (shell, YAML, Rego, policy snippets, etc.).
- Use the label “Operator's note:” at least once in the article.
- Integrate specific numbers from input/research.json verbatim. Do not invent or round. Do not introduce any quantitative claims that are not present in input/research.json.
- Match the voice rules and tone in input/style_guide.md and the samples in input/voice_samples/.
- Minimum length: 800 words.
- Avoid all banned phrases from the style guide.

Topic prompts to cover:
- The operational pain of drift and how it slips past healthy pipelines.
- GitOps as a baseline: reconcilers, desired state as code, PR-only changes.
- Policy-as-code as the guardrail: enforcement at PR and admission, fail-closed patterns.
- Practical detection loops: diff on PR, drift audits on reconcile, admission controls.
- Rollout strategy: pilot one environment, tighten over time, success criteria, feedback loops.
- End with crisp, skimmable takeaways.

Metrics to reference (pull only from input/research.json):
- Use at least four quantitative values and cite them verbatim in the article body.
- Provide a companion output/sources.json listing every quantitative value used and setting source_file to input/research.json.

Deliverables expected from the agent (for context):
- output/article.md — the full article
- output/sources.json — a JSON object documenting every quantitative value used and proving they came from input/research.json