# Selecting a workflow orchestration tool for a local data pipeline POC

## Background
We are piloting a small ETL/data pipeline on developer laptops. We want to pick a workflow orchestration tool that fits our local-first constraints and supports an iterative, collaborative approach with weekly checkpoints.

## Project constraints
- Environment: Developer laptops (macOS/Windows). No managed/cloud execution for pipeline runs.
- Language: Python 3.9+ mandatory.
- Budget: $0 for the first 3 months; prefer open-source.
- Data privacy: Avoid sending data to hosted services; local execution is required for runs.
- Team: Three engineers; an existing GitHub repo; CLI-friendly tools preferred.

## Decision criteria
- Supports local execution and scheduling on developer machines.
- Active community/maintenance (recent releases, issue activity).
- Clear documentation and a quick start under ~30 minutes.
- Python-first API (tasks/flows/dags written in Python).

## Stakeholder concerns
- Maintainability and onboarding ease.
- A path to CI integration later (e.g., GitHub Actions).

## Timeline
- Aim to select a tool after a 2-week evaluation.
