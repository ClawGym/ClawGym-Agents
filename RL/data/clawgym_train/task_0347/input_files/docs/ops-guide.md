# Operations Guide

This document describes how we assemble the weekly market digest for members.

## Operations Overview
We currently compile and share the digest manually.

## Manual Build Process
1. Open data/market_snapshot.csv
2. Run: python scripts/build_digest.py -i data/market_snapshot.csv -o dist/digest.html
3. Zip dist/digest.html and email to the web team.

TODO: Replace this section when we automate CI.

## Data Sources
- data/market_snapshot.csv: Exported from our research database.
