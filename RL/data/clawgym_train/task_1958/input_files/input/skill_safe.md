---
name: local-text-processor
description: Safe instructions for a local-only text processing helper. No network, no secrets, no elevated commands.
---

# Local Text Processor

A minimal, local-only workflow to process text files within your project directory.

## Features
- Sort lines alphabetically
- Remove duplicate lines
- Count word frequencies
- Generate a simple summary report

## Usage

1. Ensure you have Python 3 available in your environment.

2. Run the processor against a local input file and write to a local output file:
   python3 tools/text_processor.py docs/source.txt docs/processed.txt

3. Verify output by opening the generated file and checking:
   - Lines are sorted
   - Duplicates are removed
   - Summary section appears at the end

## Example Directory Layout

project/
├── docs/
│   ├── source.txt
│   └── processed.txt
└── tools/
    └── text_processor.py

## Safety Guidance
- Operates only on files within the project workspace.
- Does not execute system-level operations.
- No external connectivity is required or used.