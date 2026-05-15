import os
import csv
import re
import sys


def fail(msg):
    print(f"VALIDATION FAILED: {msg}")
    sys.exit(1)


def check_meeting_notes(path):
    if not os.path.exists(path):
        fail(f"Missing {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not re.search(r"Meeting Date:\s*\d{4}-\d{2}-\d{2}", text):
        fail("Meeting Date not found with YYYY-MM-DD in meeting notes.")
    if "Attendees:" not in text:
        fail("Attendees section missing in meeting notes.")
    if "Action" not in text:
        fail("Action Items section missing in meeting notes.")
    tasks = re.findall(r"^\s*-\s*\[\s*\]\s+.*\(due\s+\d{4}-\d{2}-\d{2}\)", text, flags=re.MULTILINE)
    if len(tasks) < 3:
        fail("Less than 3 action items with due dates in meeting notes.")
    print(f"Meeting notes OK ({len(tasks)} action items).")


def check_status_update(path):
    if not os.path.exists(path):
        fail(f"Missing {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if "Summary" not in text:
        fail("Summary section missing in status update.")
    if "Highlights" not in text:
        fail("Highlights section missing in status update.")
    bullets = re.findall(r"^\s*-\s+", text, flags=re.MULTILINE)
    if len(bullets) < 3:
        fail("Status update must have at least 3 bullet highlights.")
    if "Lena" not in text:
        fail("Status update should mention Lena by name.")
    print("Status update OK.")


def load_segments(csv_path):
    if not os.path.exists(csv_path):
        fail(f"Missing {csv_path}")
    segments = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if 'segment' not in reader.fieldnames:
            fail("CSV must contain 'segment' column.")
        for row in reader:
            seg = (row.get('segment') or '').strip()
            if seg:
                segments.append(seg)
    if not segments:
        fail("No segments found in CSV.")
    return segments


def check_messages(segments, base_dir):
    for seg in segments:
        path = os.path.join(base_dir, f"message_{seg}_en.txt")
        if not os.path.exists(path):
            fail(f"Missing {path}")
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if not lines or not lines[0].startswith("Subject:"):
            fail(f"{path} must start with a 'Subject:' line.")
        text = "\n".join(lines)
        for token in ("UPDATE:", "NEXT STEPS:"):
            if token not in text:
                fail(f"{path} missing '{token}' section.")
        if "Lena" not in text:
            fail(f"{path} should mention 'Lena'.")
        bullet_count = len([ln for ln in lines if ln.strip().startswith('- ')])
        if bullet_count < 2:
            fail(f"{path} must include at least 2 bullet items for next steps.")
        print(f"Message for segment '{seg}' OK ({bullet_count} bullets).")
    print("All messages OK.")


def main():
    segments = load_segments("input/supporter_segments.csv")
    check_meeting_notes("output/meeting_notes_en.md")
    check_status_update("output/status_update_en.md")
    check_messages(segments, "output/messages")
    print("All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
