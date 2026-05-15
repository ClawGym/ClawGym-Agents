# Seminar Evaluation Criteria: Jordan Ellis

Use these weights and normalization rules to compute composite scores between 0.0 and 1.0. Cap each normalized factor at 1.0.

On-court composite =
- Championships (titles): weight 0.4; normalized as titles / 3
- League MVP awards (mvps): weight 0.3; normalized as mvps / 3
- Career points: weight 0.3; normalized as career_points / 25000

Off-court composite =
- Scholarships awarded: weight 0.4; normalized as scholarships / 150
- Total grants donated (USD): weight 0.4; normalized as grants_total_usd / 4000000
- Students reached in 2020 through "Hoops & Homework": weight 0.2; normalized as program_reach_2020 / 3000

Overall score = 0.5 * On-court composite + 0.5 * Off-court composite

Source guidance:
- For on-court counts (titles, mvps, career_points), use input/data/season_stats.json when available. The HTML article may repeat these figures.
- For grants_total_usd, sum AmountUSD over all rows in input/data/community_grants.csv.
- For scholarships and program reach, extract from input/articles/player_legacy.html.
- If figures differ across sources, prefer JSON/CSV numeric data and note discrepancies in the critique.
