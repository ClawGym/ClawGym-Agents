DevTools Guild Style Guide — Roi Field Manual

Purpose
- Provide a concise, pragmatic field manual for engineers using roi in devtools contexts.
- Optimize for clarity, fast scanning, and direct applicability.

Voice and Tone
- Crisp, neutral, and action-oriented. Avoid marketing language.
- Prefer imperative sentences (e.g., “Validate inputs before execution.”).
- Use American English spelling and straightforward vocabulary.
- Keep sentences short and unambiguous. Prioritize signal over flourish.

Formatting Rules
- Front matter: Start the document with YAML front matter including:
  - title: must include the phrase “Roi Field Manual”
  - date: ISO-8601 (YYYY-MM-DD) in UTC
- Headings:
  - Use H1 headings (#) for each required section, in this exact order:
    1) Intro
    2) Quickstart
    3) Patterns
     4) Debugging
     5) Performance
     6) Security
     7) Migration
     8) Cheatsheet
  - Do not add extra H1 sections. Subsections may use bold labels or H2/H3 if needed.
- Blockquotes:
  - Include at least two blockquoted lines per section.
  - Quotes must be verbatim from the corresponding roi reference topic output.
  - Prefix each quoted line with a single “> ” and do not alter punctuation, casing, or symbols.
- Checklists:
  - Quickstart and Migration must contain a subsection labeled “Checklist”.
  - Reproduce enumerated steps verbatim from the respective roi outputs. Preserve order and phrasing.
- Action Items:
  - Conclude every section with a mini-list titled “Action Items” (bold label on its own line) followed by exactly three bullets.
  - Each bullet starts with a strong verb and is tailored to the section’s theme (no fluff, no repetition).
  - Example:
    Action Items
    - Verify configuration with a minimal example.
    - Capture logs for any anomalies and file issues.
    - Add notes to team runbook.
- Lists and Bullets:
  - Use “- ” for bullets, “1.” for ordered lists only when reproducing reference steps.
  - Keep bullets parallel in structure and concise.
- Code and Commands:
  - Inline code formatting is optional; keep usage minimal.
  - Do not alter or annotate quoted reference commands or steps.
- Symbols and Characters:
  - Unicode arrows (→) from the roi reference are acceptable and must be preserved in verbatim quotes.
  - Avoid emojis unless they appear in verbatim quotes (do not add new ones).

Style Constraints
- Consistency: Use the same terminology across sections (e.g., “roi”, “devtools”).
- Clarity: Prefer examples and guidance that are immediately actionable for engineers.
- Brevity: Do not exceed necessary detail; omit redundant statements.
- Accuracy: For any quoted content, do not paraphrase or reformat. Copy exactly from the roi reference tool output.

Process Guidance
- Run the roi reference tool for each topic to gather source text.
- Extract and place at least two lines of verbatim quotes per section.
- For Quickstart and Migration, identify the enumerated steps and reproduce them under “Checklist”.
- Ensure the manual includes the required verbatim substrings:
  - Intro: “Roi (roi) is a specialized tool/concept in the devtools domain.”, “Improving efficiency in devtools workflows”
  - Quickstart: “Run the hello-world example”, “Explore available commands and options”
  - Patterns: “Follow the principle of least privilege”, “Anti-Patterns to Avoid”
  - Debugging: “Reproduce the issue consistently”
  - Performance: “Caching: Reduce redundant operations”, “Parallel Processing: Utilize multiple cores”
  - Security: “Encrypt data at rest and in transit”
  - Migration: “Prepare target environment”, “Switch traffic / go live”
  - Cheatsheet: the three workflows exactly as:
    - Setup: install → configure → verify → test
    - Daily: check → monitor → report → review
    - Issue: diagnose → isolate → fix → verify → document

Cheatsheet Text File Guidelines (roi_cheatsheet.txt)
- Convert “Essential Commands” table to bullets in the exact form:
  - - help: Show available commands
  - - version: Display version info
  - - intro: Overview and fundamentals
  - - troubleshooting: Common problems and fixes
- Include the three “Common Workflows” lines exactly as:
  - Setup: install → configure → verify → test
  - Daily: check → monitor → report → review
  - Issue: diagnose → isolate → fix → verify → document

Quality Bar
- Zero paraphrasing inside quotes.
- No invented commands or steps not present in the references.
- Each section ends with a three-bullet “Action Items” mini-list tailored to that section.
- Final document is scannable and free of filler language.