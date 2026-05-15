import sys
import csv
from datetime import datetime

REQUIRED_COLUMNS = [
    "task_id",
    "title",
    "category",
    "priority",
    "effort_mins",
    "due_datetime",
    "depends_on",
]

ISO_FMT = "%Y-%m-%dT%H:%M"


def validate(csv_path: str) -> int:
    errors = []
    warns = []
    seen_ids = set()
    rows = []

    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                errors.append({
                    "task_id": None,
                    "field": "header",
                    "msg": f"missing columns: {', '.join(missing)}"
                })
                # Still attempt to read rows to report more issues
            for row in reader:
                rows.append(row)
    except FileNotFoundError:
        print(f"ERROR could not open file: {csv_path}", file=sys.stderr)
        return 2

    # Row-level checks
    for idx, row in enumerate(rows, start=2):  # header is line 1
        tid = row.get("task_id", "").strip()
        if not tid:
            errors.append({"task_id": None, "field": "task_id", "msg": f"blank task_id at CSV line {idx}"})
        elif tid in seen_ids:
            errors.append({"task_id": tid, "field": "task_id", "msg": "duplicate task_id"})
        else:
            seen_ids.add(tid)

        # priority
        pr_raw = (row.get("priority") or "").strip()
        try:
            pr = int(pr_raw)
            if pr < 1 or pr > 5:
                errors.append({"task_id": tid, "field": "priority", "msg": f"out of range 1-5: {pr_raw}"})
        except ValueError:
            errors.append({"task_id": tid, "field": "priority", "msg": f"not an integer: {pr_raw}"})

        # effort_mins
        em_raw = (row.get("effort_mins") or "").strip()
        if em_raw == "":
            errors.append({"task_id": tid, "field": "effort_mins", "msg": "missing"})
        else:
            try:
                em = int(em_raw)
                if em <= 0:
                    errors.append({"task_id": tid, "field": "effort_mins", "msg": f"must be > 0: {em_raw}"})
            except ValueError:
                errors.append({"task_id": tid, "field": "effort_mins", "msg": f"not an integer: {em_raw}"})

        # due_datetime
        dd_raw = (row.get("due_datetime") or "").strip()
        try:
            datetime.strptime(dd_raw, ISO_FMT)
        except Exception:
            errors.append({"task_id": tid, "field": "due_datetime", "msg": f"not ISO local '{ISO_FMT}': {dd_raw}"})

    # depends_on existence (warning only)
    id_set = set(r.get("task_id", "").strip() for r in rows)
    for row in rows:
        tid = row.get("task_id", "").strip()
        dep = (row.get("depends_on") or "").strip()
        if dep and dep not in id_set:
            warns.append({"task_id": tid, "field": "depends_on", "msg": f"references unknown task_id: {dep}"})

    # Emit details to stderr
    for e in errors:
        print(
            f"ERROR task_id={e.get('task_id')} field={e.get('field')} msg=\"{e.get('msg')}\"",
            file=sys.stderr,
        )
    for w in warns:
        print(
            f"WARN task_id={w.get('task_id')} field={w.get('field')} msg=\"{w.get('msg')}\"",
            file=sys.stderr,
        )

    # Emit summary to stdout
    print(
        f"Validation complete: rows={len(rows)}, errors={len(errors)}, warnings={len(warns)}"
    )

    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_tasks.py <tasks.csv>", file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
