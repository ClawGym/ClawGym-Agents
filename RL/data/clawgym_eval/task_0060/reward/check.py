import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def parse_code_todos(workspace: Path) -> Dict[str, Dict[str, Any]]:
    # Returns mapping id -> {
    #   "occurrences": [ { "path": str, "language": "js"|"java", "message": str, "priority": int, "due": str, "assignee": str } ],
    # }
    results: Dict[str, Dict[str, Any]] = {}
    todo_re = re.compile(
        r'//\s*TODO\[id=([^,\]\s]+),priority=(\d+),due=(\d{4}-\d{2}-\d{2}),assignee=([^\]]+)\]:\s*(.+)$'
    )
    for rel_dir, lang in [("src/js", "js"), ("src/java", "java")]:
        base = workspace / rel_dir
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix not in [".js", ".java"]:
                continue
            # only consider files within src/js and src/java
            text = read_text_safe(p)
            if text is None:
                continue
            for line in text.splitlines():
                m = todo_re.search(line)
                if not m:
                    continue
                todo_id = m.group(1).strip()
                priority_str = m.group(2).strip()
                due = m.group(3).strip()
                assignee = m.group(4).strip()
                message = m.group(5).strip()
                try:
                    priority = int(priority_str)
                except Exception:
                    continue
                occ = {
                    "path": p.relative_to(workspace).as_posix(),
                    "language": "js" if p.suffix == ".js" else "java",
                    "message": message,
                    "priority": priority,
                    "due": due,
                    "assignee": assignee,
                }
                bucket = results.setdefault(todo_id, {"occurrences": []})
                bucket["occurrences"].append(occ)
    return results


def load_backlog(workspace: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    backlog_path = workspace / "input" / "backlog.csv"
    rows = load_csv_dicts(backlog_path)
    if rows is None:
        return None
    # Expected columns: id,title,component,language,priority,due,assignee,status
    expected_cols = {"id", "title", "component", "language", "priority", "due", "assignee", "status"}
    if set(rows[0].keys()) != expected_cols:
        # If header mismatch, treat as invalid
        return None
    data: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            pid = r["id"]
            title = r["title"]
            component = r["component"]
            language = r["language"]
            priority = int(r["priority"])
            due = r["due"]
            assignee = r["assignee"]
            status = r["status"]
        except Exception:
            return None
        data[pid] = {
            "id": pid,
            "title": title,
            "component": component,
            "language": language,
            "priority": priority,
            "due": due,
            "assignee": assignee,
            "status": status,
        }
    return data


def load_team_roles(workspace: Path) -> Optional[Dict[str, str]]:
    team_path = workspace / "input" / "team.json"
    obj = load_json_safe(team_path)
    if obj is None or not isinstance(obj, dict):
        return None
    roles: Dict[str, str] = {}
    for name, info in obj.items():
        role = None
        if isinstance(info, dict):
            role = info.get("role")
        if isinstance(role, str):
            roles[name] = role
    return roles


def build_expected(workspace: Path) -> Optional[Tuple[List[Dict[str, Any]], str]]:
    backlog = load_backlog(workspace)
    team_roles = load_team_roles(workspace)
    code_todos = parse_code_todos(workspace)
    if backlog is None or team_roles is None:
        return None
    # Merge ids
    all_ids = set(backlog.keys()) | set(code_todos.keys())
    tasks: List[Dict[str, Any]] = []
    for tid in sorted(all_ids):
        in_backlog = tid in backlog
        in_code = tid in code_todos
        code_paths: List[str] = []
        if in_code:
            paths = [occ["path"] for occ in code_todos[tid]["occurrences"]]
            code_paths = sorted(sorted(set(paths)))
        if in_backlog and in_code:
            b = backlog[tid]
            rec = {
                "id": b["id"],
                "title": b["title"],
                "language": b["language"],
                "component": b["component"],
                "priority": int(b["priority"]),
                "due": b["due"],
                "assignee": b["assignee"],
                "assignee_role": team_roles.get(b["assignee"], "Unknown"),
                "status": b["status"],
                "source": "both",
                "code_paths": code_paths,
            }
        elif in_backlog and not in_code:
            b = backlog[tid]
            rec = {
                "id": b["id"],
                "title": b["title"],
                "language": b["language"],
                "component": b["component"],
                "priority": int(b["priority"]),
                "due": b["due"],
                "assignee": b["assignee"],
                "assignee_role": team_roles.get(b["assignee"], "Unknown"),
                "status": b["status"],
                "source": "backlog",
                "code_paths": [],
            }
        else:
            # code only
            occs = code_todos[tid]["occurrences"]
            # Choose a deterministic representative for title/language: first by lex path
            occs_sorted = sorted(occs, key=lambda o: (o["path"], o["language"], o["message"]))
            rep = occs_sorted[0]
            assignee = rep["assignee"]
            rec = {
                "id": tid,
                "title": rep["message"],
                "language": rep["language"],
                "component": "",
                "priority": int(rep["priority"]),
                "due": rep["due"],
                "assignee": assignee,
                "assignee_role": team_roles.get(assignee, "Unknown"),
                "status": "open",
                "source": "code",
                "code_paths": code_paths,
            }
        tasks.append(rec)
    # Sorted by id ascending already due to loop
    # Build next sprint table
    open_tasks = [t for t in tasks if isinstance(t.get("status"), str) and t.get("status") == "open"]
    def sort_key(t: Dict[str, Any]) -> Tuple[int, str, str]:
        return (int(t["priority"]), t["due"], t["id"])
    open_tasks_sorted = sorted(open_tasks, key=sort_key)
    top5 = open_tasks_sorted[:5]
    header = ["id", "title", "language", "assignee", "priority", "due", "source"]
    header_line = "| " + " | ".join(header) + " |"
    sep_line = "| " + " | ".join(["---"] * len(header)) + " |"
    rows_lines = []
    for t in top5:
        row = [
            t["id"],
            t["title"],
            t["language"],
            t["assignee"],
            str(int(t["priority"])),
            t["due"],
            t["source"],
        ]
        rows_lines.append("| " + " | ".join(row) + " |")
    table_content = "\n".join([header_line, sep_line] + rows_lines)
    return tasks, table_content


def normalize_table_text(s: str) -> str:
    # Normalize line endings and strip trailing spaces on each line
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = s.split("\n")
    lines = [ln.rstrip() for ln in lines]
    # Strip leading/trailing newlines
    while lines and lines[0] == "":
        lines = lines[1:]
    while lines and lines[-1] == "":
        lines = lines[:-1]
    return "\n".join(lines)


def validate_all_tasks_schema(items: Any) -> bool:
    if not isinstance(items, list) or not items:
        # allow empty? The task expects tasks; but schema check should fail if not list or empty
        if not isinstance(items, list):
            return False
        # empty list is a valid JSON array but likely wrong; count will be checked elsewhere, we treat schema ok for empty
    required_fields = {
        "id": str,
        "title": str,
        "language": str,
        "component": str,
        "priority": (int, float),
        "due": str,
        "assignee": str,
        "assignee_role": str,
        "status": str,
        "source": str,
        "code_paths": list,
    }
    for it in items:
        if not isinstance(it, dict):
            return False
        # must have at least required fields
        for k, typ in required_fields.items():
            if k not in it:
                return False
            if k == "priority":
                if not isinstance(it[k], (int, float)):
                    return False
            elif k == "code_paths":
                if not isinstance(it[k], list):
                    return False
                if not all(isinstance(cp, str) for cp in it[k]):
                    return False
            elif not isinstance(it[k], typ if isinstance(typ, type) else typ):
                return False
        # language must be js or java
        if it["language"] not in ("js", "java"):
            return False
        # source must be one of
        if it["source"] not in ("backlog", "code", "both"):
            return False
        # due must match YYYY-MM-DD
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", it["due"]):
            return False
    return True


def project_task(task: Dict[str, Any]) -> Dict[str, Any]:
    # Project to the specified fields only and normalize types for comparison
    out = {
        "id": str(task.get("id")),
        "title": str(task.get("title")),
        "language": str(task.get("language")),
        "component": str(task.get("component")),
        "priority": int(task.get("priority")),
        "due": str(task.get("due")),
        "assignee": str(task.get("assignee")),
        "assignee_role": str(task.get("assignee_role")),
        "status": str(task.get("status")),
        "source": str(task.get("source")),
        "code_paths": sorted([str(p) for p in task.get("code_paths", [])]),
    }
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_all_tasks_json_present": 0.0,
        "all_tasks_json_parseable": 0.0,
        "all_tasks_schema_valid": 0.0,
        "all_tasks_ids_and_order_match_expected": 0.0,
        "all_tasks_records_exact_match": 0.0,
        "outputs_next_sprint_md_present": 0.0,
        "next_sprint_table_exact_match": 0.0,
        "readme_next_sprint_section_updated": 0.0,
    }

    expected = build_expected(workspace)
    expected_tasks: Optional[List[Dict[str, Any]]] = None
    expected_table: Optional[str] = None
    if expected is not None:
        expected_tasks, expected_table = expected
    # Check outputs/all_tasks.json
    all_tasks_path = workspace / "outputs" / "all_tasks.json"
    if all_tasks_path.exists() and all_tasks_path.is_file():
        scores["outputs_all_tasks_json_present"] = 1.0
        parsed = load_json_safe(all_tasks_path)
        if isinstance(parsed, list):
            scores["all_tasks_json_parseable"] = 1.0
            if validate_all_tasks_schema(parsed):
                scores["all_tasks_schema_valid"] = 1.0
                # Compare IDs and order
                if expected_tasks is not None:
                    expected_ids = [t["id"] for t in expected_tasks]
                    output_ids = [it.get("id") for it in parsed if isinstance(it, dict)]
                    if output_ids == expected_ids:
                        scores["all_tasks_ids_and_order_match_expected"] = 1.0
                    # Compare full records after projection
                    try:
                        projected_output = [project_task(it) for it in parsed]
                        projected_expected = [project_task(it) for it in expected_tasks]
                        # Ensure order corresponds to expected by id order
                        if projected_output == projected_expected:
                            scores["all_tasks_records_exact_match"] = 1.0
                    except Exception:
                        pass
        else:
            scores["all_tasks_json_parseable"] = 0.0
    # Check outputs/next_sprint.md
    next_md_path = workspace / "outputs" / "next_sprint.md"
    if next_md_path.exists() and next_md_path.is_file():
        scores["outputs_next_sprint_md_present"] = 1.0
        md_text = read_text_safe(next_md_path)
        if md_text is not None and expected_table is not None:
            if normalize_table_text(md_text) == normalize_table_text(expected_table):
                scores["next_sprint_table_exact_match"] = 1.0

    # Check docs/README.md section update
    readme_path = workspace / "docs" / "README.md"
    readme_text = read_text_safe(readme_path)
    if readme_text is not None and expected_table is not None:
        start_marker = "<!-- NEXT_SPRINT_START -->"
        end_marker = "<!-- NEXT_SPRINT_END -->"
        start_idx = readme_text.find(start_marker)
        end_idx = readme_text.find(end_marker)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            # Extract content between markers
            start_after = start_idx + len(start_marker)
            between = readme_text[start_after:end_idx]
            # Normalize both
            if normalize_table_text(between) == normalize_table_text("\n" + expected_table + "\n"):
                scores["readme_next_sprint_section_updated"] = 1.0
            else:
                # Try without surrounding newlines
                if normalize_table_text(between) == normalize_table_text(expected_table):
                    scores["readme_next_sprint_section_updated"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()