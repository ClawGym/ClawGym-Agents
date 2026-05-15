# Specification

## Purpose
Provide a realistic but small file layout for terminal-based auditing:
- multiple file types
- nested directories
- text-only assets

## Requirements
- No external network or binary assets
- All files use UTF-8 with Unix line endings
- Deterministic locations and names

## Data Files
- data/sample.json: basic metadata
- data/config.yaml: environment and flags
- data/events.jsonl: line-delimited event records