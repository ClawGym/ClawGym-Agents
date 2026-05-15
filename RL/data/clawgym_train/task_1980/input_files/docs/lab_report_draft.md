# Lab 3: Beam Deflection Validation

Author: Second-year MechEng student
Course: Mechanics of Materials Lab

## Objective
Validate computed maximum deflection for a cantilever beam under UDL against reference cases.

## Method
- Use function under test: `cantilever_udl_max_deflection(E_GPa, I_m4, L_m, w_N_per_m)` from `src/beam.py`.
- Compare computed values against reference cases in `data/reference_cases.csv`.
- Tolerance for agreement: 1e-6 m.

## Validation Results
TODO: Replace this placeholder with a table summarizing each case with columns:
`case_id | expected_max_deflection_m | computed_max_deflection_m | status (PASS/FAIL)`

## Notes
Record any discrepancies and hypothesized causes. This section will inform next steps and questions to the TA.
