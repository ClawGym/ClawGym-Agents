# Stats Mini-Quiz (Class Assignment)

Use the provided scrim log (input/match_logs.csv) to create a short multiple-choice assessment.

Requirements:
- Create exactly 6 multiple-choice questions (A–D options). Build them solely from the CSV.
- Mix of question types:
  - At least 2 direct-fact questions (e.g., a specific date, opponent, or count present in the CSV).
  - At least 2 aggregate/rate questions (e.g., win rate on a map, K/D ratio by game, totals/averages).
- Deliverables:
  1. output/quiz/quiz.json: Array of 6 question objects with fields:
     - id (Q1–Q6)
     - stem (the question)
     - choices: {A, B, C, D}
     - correct (A|B|C|D)
     - type (direct|aggregate)
     - evidence: brief calculation explanation + references to supporting match_id(s) and/or groupings (e.g., map/game/opponent).
  2. output/quiz/answer_key.csv with columns: id,correct.
  3. output/stats/summary.csv with columns: group_type (game|map), group_name, matches, wins, losses, win_rate (0–1), kills, deaths, kd_ratio.
  4. output/validation/report.json: For each question, include id, computed_answer (derived from the CSV), matches_correct (true/false), and a short note. Include an overall all_passed boolean.

Grading focus:
- Questions must be answerable directly from the dataset and your documented calculations.
- Evidence must clearly show how the answer is obtained (e.g., which rows or groups contribute).
- Validation must recompute and confirm that each correct answer matches the data.
