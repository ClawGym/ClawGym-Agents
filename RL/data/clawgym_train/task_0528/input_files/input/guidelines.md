Briefing Production Guidelines

1) Inputs and Outputs
- Inputs to read:
  - input/briefing_scope.json: Provides regions, timeframe, emphasis areas, and audience questions.
  - These guidelines: Formatting, citation, and data standards.
- Required outputs:
  - output/sources.json
  - output/bibliography.csv
  - output/brief.md
- Do not place any files under reward/. Use only the output/ directory for deliverables.

2) Research Method and Tools
- Use live web search with the seekit CLI across at least three different providers.
- Prefer official regulator/government sites, reputable news outlets, and recognized policy think tanks.
- Use multiple providers to broaden coverage and reduce bias/noise.
- Example commands:
  - seekit "EU AI Act foundation models codes of practice 2025 site:europa.eu" --engine bing --format json --limit 10
  - seekit "NIST AI Safety Institute guidance foundation models 2025" --engine google --format json --limit 10
  - seekit "FTC AI model transparency policy 2025" --engine duckduckgo --format json --limit 10
  - seekit "OMB memo AI foundation model federal guidance 2025" --engine brave --format json --limit 10
- Acceptable providers include: bing, google, duckduckgo, brave, reddit, youtube, so, sogou, toutiao. Focus on web providers (bing, google, duckduckgo, brave) for this task.

3) Timeframe and Scope
- Only include developments published or updated within the last 12 months from the current date.
- Regions: EU and US. Include state-level US actions if they directly affect foundation models.
- Emphasis areas: foundation model obligations, safety evaluation/testing, transparency/provenance, systemic risk, reporting thresholds, open-source carve-outs, timelines.

4) sources.json Schema and Standards
- File path: output/sources.json
- Top-level must be a JSON array with at least 12 distinct sources.
- Each item is an object with required fields:
  - provider: string (e.g., "bing", "google", "duckduckgo", "brave").
  - title: string (clear, human-readable source title).
  - excerpt: string (1–3 sentences summarizing the source’s relevant content).
  - url: string (must start with http or https; use canonical URL, not tracking links).
  - author: string or null (use official author when available; else null).
  - time: string in YYYY-MM-DD format (use the publication or last updated date; YYYY-MM is acceptable if day unknown).
  - tags: array of strings (e.g., ["EU", "AI Act", "foundation models", "NIST"]).
- Requirements:
  - Include at least three distinct provider values across the array.
  - Avoid duplicates; each URL must be unique and reputable.
  - Prioritize domains such as europa.eu, ec.europa.eu, ai.europa.eu, nist.gov, whitehouse.gov, omb.gov, ftc.gov, cisa.gov, congress.gov; reputable media (e.g., Financial Times, The Economist, Reuters, WSJ) and recognized think tanks (e.g., Brookings, CSIS, CSET, CEPS, Bruegel).
  - Ensure the time value falls within the last 12 months.

5) bibliography.csv Format
- File path: output/bibliography.csv
- Header must be exactly (lowercase, comma-separated): title,provider,url,time,notes
- Include the same set of sources as in output/sources.json. Every URL in sources.json must appear exactly once here.
- The notes field: a concise 1–2 sentence annotation describing why this source matters to the briefing (e.g., what it clarifies, any key dates, or what perspective it adds).

6) Brief Structure and Writing Rules (brief.md)
- File path: output/brief.md
- Word count: 1,000–1,500 words.
- Section headings in this exact order:
  1. Executive Summary
  2. Key Developments (EU vs US)
  3. Source Clusters
  4. Compliance Implications
  5. Open Questions
  6. Source Reliability Notes
- Use clear, executive-ready prose and avoid excessive technical jargon.
- Use inline numeric citations like [#] that correspond to the 1-based index of entries in output/sources.json. For example, [1] refers to the first item in sources.json.
- Insert citations where claims are made, ideally near the end of the relevant sentence or paragraph.
- Explicitly identify conflicting accounts or interpretations across sources and explain your reconciliation (e.g., prioritize primary law/regulator text over secondary commentary, or note that guidance is proposed vs finalized).
- Include both “EU” and “US” references in the content and provide a direct comparison in the “Key Developments (EU vs US)” section.
- Make “Compliance Implications” actionable (e.g., named controls, documentation to prepare, evaluation approaches, governance checkpoints, and near-term timelines).

7) Quality and Credibility Checklist
- Coverage:
  - EU AI Act implementation affecting foundation models (e.g., codes of practice, systemic risk requirements, documentation, transparency/content provenance).
  - US: NIST/AISI safety evaluation/red teaming guidance, OMB memos, FTC policy statements or enforcement, DHS/CISA advisories relevant to model safety.
- Credibility:
  - Prefer primary sources (regulator portals, official notices) to resolve ambiguity.
  - Use reputable media and think-tank analysis for context and synthesis.
- Consistency:
  - Ensure every in-text citation [#] maps to the same numbered entry in sources.json.
  - Ensure bibliography.csv includes every URL from sources.json exactly once.

8) Tagging Guidance (sources.json)
- Suggested tags to mix and match:
  - Region: "EU", "US"
  - Topic: "AI Act", "foundation models", "GPAI", "codes of practice", "systemic risk", "transparency", "provenance", "watermarking", "reporting", "red teaming", "evaluation", "security", "open source"
  - Body: "European Commission", "EU AI Office", "NIST", "AISI", "OMB", "FTC", "DHS", "CISA", "Congress"
- Keep tags concise and consistent across similar sources.

9) Handling Dates and Updates
- Prefer the “last updated” date if it’s clearly indicated and within the last 12 months.
- If only a publication month/year is available, use YYYY-MM and omit the day (e.g., 2025-06).

10) Examples
- Example sources.json item:
  {
    "provider": "bing",
    "title": "EU AI Office issues draft Code of Practice for General-Purpose AI",
    "excerpt": "The EU AI Office released a draft code outlining safety testing, systemic risk management, and transparency obligations for foundation models.",
    "url": "https://europa.eu/ai-office/example-code-of-practice",
    "author": "EU AI Office",
    "time": "2025-11-07",
    "tags": ["EU", "AI Act", "GPAI", "codes of practice"]
  }
- Example bibliography.csv row:
  title,provider,url,time,notes
  EU AI Office issues draft Code of Practice for General-Purpose AI,bing,https://europa.eu/ai-office/example-code-of-practice,2025-11-07,Primary EU source detailing draft obligations for foundation models; anchors systemic risk and testing expectations.

11) Final Validation Before Delivery
- sources.json:
  - Array length ≥ 12, at least three providers represented, all required fields present, valid URLs, dates within last 12 months.
- bibliography.csv:
  - Exact header, same number of rows as sources.json (or more), every URL from sources.json present exactly once, notes populated.
- brief.md:
  - Contains all required headings, word count 1,000–1,500, includes “EU” and “US”, uses numeric [#] citations, identifies and reconciles conflicts, offers concrete next-step compliance actions.

12) Common Pitfalls to Avoid
- Do not include paywalled links that block access to essential facts if an open alternative exists.
- Do not cite vendor marketing pages as authoritative policy.
- Do not mismatch citation numbers between brief.md and sources.json.
- Do not include sources older than 12 months without clearly marking as context (and avoid counting them toward the minimum 12).