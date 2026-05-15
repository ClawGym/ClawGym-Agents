Use these exact formatting rules when producing output/session.md and support files:

1) Headings and order (exact strings, exact order):
- "## Vocabulary (10 items)"
- "## Grammar pattern of the day"
- "## Kanji focus (3 kanji)"
- "## Reading passage"
- "## Listening/speaking prompt"
- "## Quick quiz (5 questions)"
- "## Cultural note"

2) Vocabulary section (between Vocabulary and Grammar headings):
- Exactly 10 items, numbered 1. through 10. (lines starting with "1.", "2.", ... "10.")
- For each item include: word with furigana in parentheses using Kanji(kana) format, romaji, English meaning, one Japanese example sentence with English translation, and a brief memory tip.
- Keep entries concise and consistent.

3) Grammar pattern of the day:
- Provide structure, plain-English explanation, 3 example sentences (easy → medium → hard), common mistakes, and a brief contrast with a similar pattern.

4) Kanji focus (3 kanji):
- For each: character, on readings (on), kun readings (kun), stroke count, exactly two compounds, and one example sentence.

5) Reading passage:
- Include label "Reading (JP):" followed by the Japanese passage.
- Then include label "Translation (EN):" followed by the full English translation text.
- The translation must be between 80 and 200 words inclusive.
- After the translation, list exactly 3 bullet-point highlights (key vocabulary/grammar points).

6) Listening/speaking prompt:
- Include a short scenario, a 2–4 exchange sample dialogue (JP with EN translation), 3 speaking prompts, and suggested response vocabulary.

7) Quick quiz (5 questions):
- Exactly five lines starting with "Q1:", "Q2:", "Q3:", "Q4:", "Q5:".
- After questions, include a divider line of exactly five dashes: "-----" on its own line.
- Then an "Answers" subsection with exactly five lines starting with "A1:", "A2:", "A3:", "A4:", "A5:".

8) Cultural note:
- 2–3 sentences only.

9) Cross-file consistency:
- output/vocab.csv must have header: word,furigana,romaji,meaning and exactly 10 rows matching the Vocabulary items.
- output/kanji.json must be an array of 3 objects with keys: character, on (array), kun (array), stroke_count (integer), compounds (array of exactly 2 strings), example (string).
- output/metadata.json must include: level == "N3", vocabulary_count == 10, kanji_count == 3, quiz_count == 5, focus_topics (copied from learner_profile.json), avoided_terms (all lines from previous_session_keywords.txt as an array), format_version (string), and a brief compliance_notes string.

10) Personalization and constraints:
- Level is N3.
- Weave at least one of the focus_topics into the reading passage and at least one example sentence.
- Do not include any words from input/previous_session_keywords.txt anywhere in output/session.md (case-insensitive check).
- Maintain clear, consistent formatting exactly as specified so automated checks can parse all sections successfully.