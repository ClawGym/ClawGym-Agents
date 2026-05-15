# Gradebook Prototype

This simple tool loads students and their letter grades from a CSV and exports a CSV with GPAs.

- Input CSV format: name, grades (semicolon-separated letters)
- Usage: `python src/gradebook.py data/sample_students.csv gradebook_out.csv`
- Known issues: duplicated GPA logic, print-based logging, inconsistent parsing.

Project structure:
- src/gradebook.py: main tool and Gradebook class
- src/utils.py: helper functions (inconsistent usage)
- config/settings.json: logging level and GPA scale
- data/sample_students.csv: sample data
- tests/expected_gpa.json: expected output for sample data
- messages/drafts.md: communication drafts to improve
