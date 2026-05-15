Bilingual Methods Supplement — Formatting Preferences

Scope and Goal
- Audience: Hematology/Oncology methods supplement with bilingual terminology (Chinese ↔ English).
- Objective: Deterministic, audit-friendly translations using standard medical terminology.

English Formatting
- Capitalization: Use Title Case for diseases, syndromes, and interventions (e.g., Acute Myeloid Leukemia, Myocardial Infarction).
- Acronyms: If a widely accepted acronym exists (e.g., AML, MI), append it once in parentheses on the English translation for that row: “Acute Myeloid Leukemia (AML)”.
- Synonyms: When two English terms are widely accepted, include both separated by “ / ” (e.g., “Tumor / Neoplasm”). Do not list more than two.

Chinese Formatting
- Orthography: Use standardized simplified Chinese medical terminology.
- Acronyms in Chinese: Do not add English acronyms to Chinese translations unless they are routinely used in Chinese clinical literature (rare). Default to Chinese-only for English→Chinese entries.
- Punctuation: No trailing punctuation after the translated term.

Dictionary and Confirmation Policy
- Use the packaged standard dictionary for core terms. If a term is not found in the standard dictionary, prefix the translation with “[Requires manual confirmation] ” and add a note explaining why (e.g., “Not in packaged dictionary; proposed based on common medical usage.”).
- Do not infer subtypes or staging unless explicitly provided in the term or context.

Context Application
- Use the “context” column only to disambiguate meaning (e.g., oncology vs general usage) or to decide whether to include an acronym. Do not widen scope beyond the stated context.
- If context is insufficient to disambiguate, keep the most general standard term and add a note about the ambiguity.

Reproducibility and Output Discipline
- One input row → one JSON object line. Maintain the exact output fields: original, source_lang, target_lang, translated, notes (array of strings).
- Notes should capture: dictionary hit/miss, context applied, synonym decisions, acronym decisions, and any manual confirmation flags.
- No protected health information (PHI), no external references, no unstated assumptions.

Examples (for consistency)
- Chinese→English:
  - “急性髓系白血病” → “Acute Myeloid Leukemia (AML)”
  - “肿瘤” → “Tumor / Neoplasm”
- English→Chinese:
  - “Myocardial Infarction” → “心肌梗死”
  - “Hypertension” → “高血压”

Error Handling and Limits
- If a language pair outside Chinese↔English appears, proceed with the known pairs and document the out-of-scope items in the summary.
- For any out-of-dictionary item, apply the confirmation prefix and add a clear explanatory note.