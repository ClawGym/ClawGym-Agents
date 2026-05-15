#!/usr/bin/env python3
import json
import os

def format_reading(r):
    author = r.get('author', '').strip()
    year = r.get('year', '')
    title = r.get('title', '').strip()
    parts = []
    if author:
        parts.append(author)
    if year != '':
        parts.append(f"({year})")
    if title:
        parts.append(f": {title}")
    return " ".join(parts).strip()

def main():
    with open('config/curriculum.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    os.makedirs('outputs', exist_ok=True)
    lines = []
    title = data.get('workshop_title', 'Workshop')
    lines.append(title)
    lines.append("")
    for s in data.get('sessions', []):
        session_id = s.get('id')
        session_title = s.get('title', '')
        lines.append(f"Session {session_id}: {session_title}")
        desc = s.get('description', '')
        if desc:
            lines.append(desc)
        readings = s.get('readings', [])
        if readings:
            lines.append("Readings:")
            for r in readings:
                lines.append(f"- {format_reading(r)}")
        lines.append("")
    with open('outputs/syllabus.md', 'w', encoding='utf-8') as out:
        out.write("\n".join(lines))

if __name__ == "__main__":
    main()
