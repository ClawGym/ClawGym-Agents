import json
import os

with open('input/course_outline.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

os.makedirs('output', exist_ok=True)

lines = [f"# {data['course']['title']} Schedule", ""]

# NOTE: This simple script writes date and title only; it does not sort sessions or include optional fields.
for s in data['course']['sessions']:
    lines.append(f"{s['date']} - {s['title']}")

with open('output/schedule.md', 'w', encoding='utf-8') as f:
    f.write("\n".join(lines))
