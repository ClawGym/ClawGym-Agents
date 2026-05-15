# TOOLS

Cost Tracking
- Script: track_cost.py — log task-level token usage and cost.
- Script: cost_report.py — daily/weekly rollups.
- Script: auto_cost_report.py — read session JSONL directly.

Context Analyzer
- Script: context_analyzer.py — estimate tokens per file (1 token per 4 chars).
- Goal: keep always-loaded files under 2000 tokens total, ideally ~1500.

Model Routing
- Use Haiku for simple tasks: classify, format, yes/no checks.
- Use Sonnet by default for multi-step work or tool use.
- Avoid Opus unless explicitly requested by the user.

Knowledge Graph
- Build mindgraph.json from docs with [[wikilinks]].
- Create concept nodes for unresolved links.
- Periodic maintenance: remove dead links, connect orphans.