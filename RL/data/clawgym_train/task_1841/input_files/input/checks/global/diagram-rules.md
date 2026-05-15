# Diagram Rules (Global)

- Type: mermaid graph
- Direction: LR (left-to-right)
- Data source: ROADMAP.md
- Include: All epics discovered in semantic version order (ascending)
- Node label format: "[<status_emoji> v<version> <epic_name>]"
- Edges: Sequential "A --> B" in version order
- Status to emoji mapping (default):
  - Active Epic: 🏗️
  - Backlog Epic: 📋
  - Completed Epic: ✅

Local rules, if present, override these defaults.