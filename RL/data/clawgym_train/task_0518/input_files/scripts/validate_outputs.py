import os, sys, json, re

SOURCE_FILES = [
    "input/docs/tamaizumi_history.md",
    "input/docs/water_quality_report.txt",
    "input/data/past_events.csv",
    "input/draft_invite.txt",
]

OUT_FACTS = "output/facts/facts_summary.json"
OUT_EMAIL = "output/email_invite.txt"
OUT_NOTES = "output/meeting_notes.md"


def fail(msg, code=1):
    print(f"FAIL: {msg}")
    sys.exit(code)


def load_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def main():
    # Check sources present
    for p in SOURCE_FILES:
        if not os.path.exists(p):
            fail(f"Missing input file: {p}")

    sources = {p: load_lines(p) for p in SOURCE_FILES}

    # Check facts JSON
    if not os.path.exists(OUT_FACTS):
        fail(f"Missing output file: {OUT_FACTS}")

    try:
        with open(OUT_FACTS, "r", encoding="utf-8") as f:
            facts = json.load(f)
    except Exception as e:
        fail(f"Cannot parse JSON at {OUT_FACTS}: {e}")

    if not isinstance(facts, list):
        fail("facts_summary.json must be a JSON array")

    if len(facts) < 5:
        fail("facts_summary.json must contain at least 5 facts")

    id_set = set()
    have_history = False
    have_water_numeric = False
    have_events_numeric = False

    for i, fact in enumerate(facts, 1):
        if not isinstance(fact, dict):
            fail(f"Fact #{i} is not an object")
        for key in ["id", "fact_text", "source_file", "support_lines", "support_excerpt"]:
            if key not in fact:
                fail(f"Fact #{i} missing field: {key}")
        fid = fact["id"]
        if not isinstance(fid, str) or not re.fullmatch(r"F\d+", fid):
            fail(f"Invalid id for fact #{i}: {fid}")
        if fid in id_set:
            fail(f"Duplicate id: {fid}")
        id_set.add(fid)

        ftxt = fact["fact_text"]
        if not isinstance(ftxt, str) or len(ftxt) == 0 or len(ftxt) > 280:
            fail(f"fact_text for {fid} must be 1..280 chars")

        src = fact["source_file"]
        if src not in sources:
            fail(f"Unknown source_file for {fid}: {src}")

        sl = fact["support_lines"]
        if (not isinstance(sl, list)) or len(sl) != 2 or not all(isinstance(n, int) for n in sl):
            fail(f"support_lines for {fid} must be [start, end] integers")
        start, end = sl
        if start < 1 or end < start or end > len(sources[src]):
            fail(f"support_lines out of range for {fid}: {sl}")

        excerpt = fact["support_excerpt"]
        if not isinstance(excerpt, str):
            fail(f"support_excerpt for {fid} must be a string")
        joined = "\n".join(sources[src][start-1:end])
        if excerpt != joined:
            fail(f"support_excerpt mismatch for {fid}")

        # Coverage flags
        if src.endswith("tamaizumi_history.md"):
            have_history = True
        if src.endswith("water_quality_report.txt") and re.search(r"\d", ftxt):
            have_water_numeric = True
        if src.endswith("past_events.csv") and re.search(r"\d", ftxt):
            have_events_numeric = True

    if not have_history:
        fail("At least one fact must come from tamaizumi_history.md")
    if not have_water_numeric:
        fail("At least one numeric fact must come from water_quality_report.txt")
    if not have_events_numeric:
        fail("At least one numeric fact must come from past_events.csv")

    # Check rewritten email
    if not os.path.exists(OUT_EMAIL):
        fail(f"Missing output file: {OUT_EMAIL}")
    with open(OUT_EMAIL, "r", encoding="utf-8") as f:
        email_txt = f.read()
    if len(email_txt) > 1200:
        fail("email_invite.txt exceeds 1200 characters")
    required_bits = ["2024-05-10", "18:00", "Community Center Room 2", "Tamaizumi-ike"]
    for bit in required_bits:
        if bit not in email_txt:
            fail(f"email_invite.txt must include: {bit}")

    # Check meeting notes
    if not os.path.exists(OUT_NOTES):
        fail(f"Missing output file: {OUT_NOTES}")
    with open(OUT_NOTES, "r", encoding="utf-8") as f:
        notes = f.read()

    for req in ["Tamaizumi-ike Community Meeting", "Date: 2024-05-10", "Agenda", "Key facts", "Action items"]:
        if req not in notes:
            fail(f"meeting_notes.md must include: {req}")

    # Collect referenced fact ids in notes
    ref_ids = set(re.findall(r"\[F(\d+)\]", notes))
    ref_ids = {f"F{n}" for n in ref_ids}
    if not ref_ids:
        fail("meeting_notes.md must reference facts using [F#] tags")
    unknown = sorted([rid for rid in ref_ids if rid not in id_set])
    if unknown:
        fail("meeting_notes.md references unknown fact ids: " + ", ".join(unknown))

    # Action items validation: at least 3 bullet lines containing a [F#]
    action_item_lines = [line for line in notes.splitlines() if line.strip().startswith("-") and "[F" in line]
    if len(action_item_lines) < 3:
        fail("meeting_notes.md must include at least 3 action items, each containing a [F#] reference")

    print("SUCCESS: All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
