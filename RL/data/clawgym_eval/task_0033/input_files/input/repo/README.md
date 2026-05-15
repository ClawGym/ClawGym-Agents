# Ceramics Reproduction Notes

This repo holds a quick-and-dirty reproduction of the ceramic classification pipeline discussed in the panel paper. It pulls a CSV feed, does a light transform, and runs some basic analysis. I'm moving fast, so a few shortcuts are present for now.

Structure:
- config/settings.yaml: runtime config for the scripts
- scripts/ingest.sh: quick fetch and transform of source CSV
- src/analyze.py: basic analysis harness
- notes/panel_outline.md: speaking points
- keys/legacy_credentials.txt: old creds I meant to remove

DO NOT EXECUTE in production environments. This is a work-in-progress snapshot.