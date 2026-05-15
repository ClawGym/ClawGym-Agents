import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "t", "yes", "y", "1"):
        return True
    if s in ("false", "f", "no", "n", "0"):
        return False
    return None


def _normalize_str(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    rooms_path = workspace / "data" / "rooms.json"
    specs_path = workspace / "data" / "specs.csv"
    rooms_data = _load_json(rooms_path)
    specs_rows = _load_csv_dicts(specs_path)
    if rooms_data is None or specs_rows is None:
        return None

    rooms: Dict[str, Dict[str, Any]] = {}
    for r in rooms_data.get("rooms", []):
        name = r.get("name")
        if isinstance(name, str):
            rooms[name] = r

    total_rooms = len(rooms)
    total_items = 0
    per_room_counts: Dict[str, Dict[str, int]] = {}
    issues: List[Dict[str, Any]] = []
    issue_counts = {"R1": 0, "R2": 0, "R3": 0, "R4": 0}

    for row in specs_rows:
        total_items += 1
        room_name = (row.get("room") or "").strip()
        per_room_counts.setdefault(room_name, {"plumbing": 0, "electrical": 0})
        system = _normalize_str(row.get("system"))
        if system == "plumbing":
            per_room_counts[room_name]["plumbing"] += 1
            finish = _normalize_str(row.get("fixture_finish"))
            expected = _normalize_str((rooms.get(room_name) or {}).get("plumbing_finish"))
            if finish and expected and finish != expected:
                issues.append({
                    "rule": "PLUMBING_FINISH_MISMATCH",
                    "rule_id": "R1",
                    "room": room_name,
                    "item_id": row.get("item_id", ""),
                    "detail": f"{finish} vs {expected}",
                })
                issue_counts["R1"] += 1
        elif system == "electrical":
            per_room_counts[room_name]["electrical"] += 1
            faceplate = _normalize_str(row.get("faceplate_color"))
            expected_face = _normalize_str((rooms.get(room_name) or {}).get("electrical_faceplate_color"))
            if faceplate and expected_face and faceplate != expected_face:
                issues.append({
                    "rule": "FACEPLATE_COLOR_MISMATCH",
                    "rule_id": "R2",
                    "room": room_name,
                    "item_id": row.get("item_id", ""),
                    "detail": f"{faceplate} vs {expected_face}",
                })
                issue_counts["R2"] += 1
            req_gfci = _parse_bool(row.get("requires_gfci")) is True
            has_gfci = _parse_bool(row.get("gfci")) is True
            if req_gfci and not has_gfci:
                issues.append({
                    "rule": "MISSING_GFCI",
                    "rule_id": "R3",
                    "room": room_name,
                    "item_id": row.get("item_id", ""),
                    "detail": "requires GFCI but gfci=false/missing",
                })
                issue_counts["R3"] += 1
            mounting = _normalize_str(row.get("mounting"))
            allow_exposed = bool((rooms.get(room_name) or {}).get("exposed_conduit", False))
            if mounting == "exposed" and not allow_exposed:
                issues.append({
                    "rule": "EXPOSED_CONDUIT_NOT_ALLOWED",
                    "rule_id": "R4",
                    "room": room_name,
                    "item_id": row.get("item_id", ""),
                    "detail": "mounting=exposed where concealed is required",
                })
                issue_counts["R4"] += 1

    rooms_with_issues_map: Dict[str, int] = {}
    for i in issues:
        rooms_with_issues_map[i["room"]] = rooms_with_issues_map.get(i["room"], 0) + 1
    expected = {
        "total_rooms": total_rooms,
        "total_items": total_items,
        "per_room_counts": per_room_counts,
        "issues": issues,
        "issue_counts": issue_counts,
        "rooms_with_issues": rooms_with_issues_map,
        "room_names": list(rooms.keys()),
    }
    return expected


def _extract_counts_from_report(text: str, room: str) -> Optional[Tuple[int, int]]:
    lines = text.splitlines()
    pl_ct = None
    el_ct = None
    # Find block for the room
    indices = [i for i, line in enumerate(lines) if room in line]
    for idx in indices:
        window = lines[idx: idx + 6]
        block = "\n".join(window)
        pl_match = re.search(r"plumb\w*[^0-9]*(\d+)", block, flags=re.IGNORECASE)
        el_match = re.search(r"electr\w*[^0-9]*(\d+)", block, flags=re.IGNORECASE)
        if pl_match and el_match:
            pl_ct = int(pl_match.group(1))
            el_ct = int(el_match.group(1))
            break
    if pl_ct is not None and el_ct is not None:
        return pl_ct, el_ct
    return None


def _issue_line_matches(room: str, item_id: str, rule_long: str, rule_short: str, line: str) -> bool:
    if room not in line or item_id not in line:
        return False
    if rule_long in line or rule_short in line:
        return True
    return False


def _find_issue_in_lines(room: str, item_id: str, rule_long: str, rule_short: str, lines: List[str]) -> bool:
    for line in lines:
        if _issue_line_matches(room, item_id, rule_long, rule_short, line):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "out_integration_report_present": 0.0,
        "out_integration_report_counts_correct": 0.0,
        "out_integration_report_issues_correct": 0.0,
        "out_action_items_present": 0.0,
        "out_action_items_format_and_coverage": 0.0,
        "out_status_summary_present": 0.0,
        "out_status_summary_schema": 0.0,
        "out_status_summary_values_correct": 0.0,
        "out_client_update_present": 0.0,
        "out_client_update_brief_and_mentions_top3": 0.0,
        "script_cli_args_present": 0.0,
        "script_faceplate_color_field_fixed": 0.0,
        "script_no_global_results_state": 0.0,
        "script_boolean_parsing_case_insensitive": 0.0,
        "script_modular_structure": 0.0,
    }

    expected = _compute_expected(workspace)

    out_dir = workspace / "out"
    report_path = out_dir / "integration_report.md"
    action_path = out_dir / "action_items.md"
    summary_path = out_dir / "status_summary.json"
    client_path = out_dir / "client_update.md"

    # integration_report.md presence
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["out_integration_report_present"] = 1.0

    # integration_report counts correctness
    if report_text is not None and expected is not None:
        counts_ok = True
        for room, ct in expected["per_room_counts"].items():
            extracted = _extract_counts_from_report(report_text, room)
            if not extracted:
                counts_ok = False
                break
            pl, el = extracted
            if pl != ct["plumbing"] or el != ct["electrical"]:
                counts_ok = False
                break
        scores["out_integration_report_counts_correct"] = 1.0 if counts_ok else 0.0

    # integration_report issues listed correctly
    if report_text is not None and expected is not None:
        lines = report_text.splitlines()
        issues_ok = True
        for issue in expected["issues"]:
            room = issue["room"]
            item_id = issue["item_id"]
            rule_long = issue["rule"]
            rule_short = issue["rule_id"]
            if not _find_issue_in_lines(room, item_id, rule_long, rule_short, lines):
                issues_ok = False
                break
        scores["out_integration_report_issues_correct"] = 1.0 if issues_ok else 0.0

    # action_items.md presence
    action_text = _read_text(action_path)
    if action_text is not None:
        scores["out_action_items_present"] = 1.0

    # action_items format and coverage
    if action_text is not None and expected is not None:
        action_lines = [ln.strip() for ln in action_text.splitlines() if ln.strip()]
        checklist_lines = [ln for ln in action_lines if ln.startswith("- [ ]")]
        coverage_ok = len(checklist_lines) == len(expected["issues"])
        if coverage_ok:
            for issue in expected["issues"]:
                room = issue["room"]
                item_id = issue["item_id"]
                rule_long = issue["rule"]
                rule_short = issue["rule_id"]
                found = False
                for ln in checklist_lines:
                    if (room in ln) and (f"Item {item_id}" in ln) and (rule_long in ln or rule_short in ln):
                        found = True
                        break
                if not found:
                    coverage_ok = False
                    break
        scores["out_action_items_format_and_coverage"] = 1.0 if coverage_ok else 0.0

    # status_summary.json presence
    summary_data = _load_json(summary_path) if summary_path.exists() else None
    if summary_data is not None:
        scores["out_status_summary_present"] = 1.0

    # status_summary schema
    if summary_data is not None:
        keys = set(summary_data.keys())
        expected_keys = {"total_rooms", "total_items", "rooms_with_issues", "issue_counts"}
        schema_ok = keys == expected_keys
        if schema_ok:
            schema_ok = isinstance(summary_data.get("total_rooms"), int) and isinstance(summary_data.get("total_items"), int)
            schema_ok = schema_ok and isinstance(summary_data.get("rooms_with_issues"), list)
            issue_counts = summary_data.get("issue_counts")
            schema_ok = schema_ok and isinstance(issue_counts, dict) and set(issue_counts.keys()) == {"R1", "R2", "R3", "R4"}
            if schema_ok:
                schema_ok = all(isinstance(issue_counts[k], int) for k in ["R1", "R2", "R3", "R4"])
        scores["out_status_summary_schema"] = 1.0 if schema_ok else 0.0

    # status_summary values correct
    if summary_data is not None and expected is not None:
        values_ok = True
        values_ok = values_ok and summary_data.get("total_rooms") == expected["total_rooms"]
        values_ok = values_ok and summary_data.get("total_items") == expected["total_items"]
        exp_rooms_issues = {(room, cnt) for room, cnt in expected["rooms_with_issues"].items()}
        got_rooms_issues = set()
        rwi = summary_data.get("rooms_with_issues", [])
        if isinstance(rwi, list):
            for entry in rwi:
                if isinstance(entry, dict) and "room" in entry and "issue_count" in entry:
                    got_rooms_issues.add((entry["room"], entry["issue_count"]))
        values_ok = values_ok and got_rooms_issues == exp_rooms_issues
        values_ok = values_ok and summary_data.get("issue_counts") == expected["issue_counts"]
        scores["out_status_summary_values_correct"] = 1.0 if values_ok else 0.0

    # client_update.md presence
    client_text = _read_text(client_path)
    if client_text is not None:
        scores["out_client_update_present"] = 1.0

    # client_update brief and mentions top3 issue types, with bullets
    if client_text is not None:
        words = client_text.split()
        brief_ok = len(words) <= 200
        # determine top3 issue types by count (ties allowed, require at least 3 unique mentions)
        mentions_ok = False
        if expected is not None:
            counts = expected["issue_counts"]
            # Sort by count desc, then rule id to stabilize, but accept any 3 if tie across all
            sorted_rules = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            top_counts = [c for _, c in sorted_rules]
            if top_counts:
                # Find threshold count for 3rd place (or last if fewer than 3 nonzero types)
                nonzero = [c for c in top_counts if c > 0]
                if len(nonzero) >= 3:
                    threshold = sorted(nonzero, reverse=True)[2]
                elif len(nonzero) > 0:
                    threshold = min(nonzero)
                else:
                    threshold = 0
                top_rules = [r for r, c in counts.items() if c >= threshold and c > 0]
                # Accept if at least three unique issue identifiers (long or short) from top_rules are mentioned
                names_map = {
                    "R1": "PLUMBING_FINISH_MISMATCH",
                    "R2": "FACEPLATE_COLOR_MISMATCH",
                    "R3": "MISSING_GFCI",
                    "R4": "EXPOSED_CONDUIT_NOT_ALLOWED",
                }
                mentioned = set()
                for r in top_rules:
                    if r in client_text or names_map[r] in client_text:
                        mentioned.add(r)
                mentions_ok = len(mentioned) >= min(3, len(top_rules))
            else:
                mentions_ok = False
        else:
            # Fallback: require at least 3 different known issue tokens if we can't compute expected
            tokens = [
                "PLUMBING_FINISH_MISMATCH",
                "FACEPLATE_COLOR_MISMATCH",
                "MISSING_GFCI",
                "EXPOSED_CONDUIT_NOT_ALLOWED",
                "R1", "R2", "R3", "R4",
            ]
            seen = set(t for t in tokens if t in client_text)
            mentions_ok = len(seen) >= 3
        bullets_ok = any(line.strip().startswith(("- ", "* ")) for line in client_text.splitlines())
        scores["out_client_update_brief_and_mentions_top3"] = 1.0 if (brief_ok and mentions_ok and bullets_ok) else 0.0

    # Script checks
    script_path = workspace / "scripts" / "integration_reporter.py"
    script_text = _read_text(script_path)
    if script_text is not None:
        cli_ok = ("argparse" in script_text) and ("--rooms" in script_text) and ("--specs" in script_text) and ("--out-dir" in script_text)
        scores["script_cli_args_present"] = 1.0 if cli_ok else 0.0

        has_correct = "faceplate_color" in script_text
        has_wrong = "faceplate_colour" in script_text
        scores["script_faceplate_color_field_fixed"] = 1.0 if (has_correct and not has_wrong) else 0.0

        no_global = True
        if re.search(r"^\s*ISSUES\s*=", script_text, flags=re.MULTILINE):
            no_global = False
        if re.search(r"\bglobal\s+ISSUES\b", script_text):
            no_global = False
        scores["script_no_global_results_state"] = 1.0 if no_global else 0.0

        # Require a dedicated boolean parsing function to consider normalization as refactored
        has_parse_bool_def = bool(re.search(r"def\s+_?parse_bool\s*\(", script_text))
        uses_parse_bool = bool(re.search(r"\b_?parse_bool\s*\(", script_text))
        mentions_fields = ("requires_gfci" in script_text and "gfci" in script_text)
        bool_ok = has_parse_bool_def and uses_parse_bool and mentions_fields
        scores["script_boolean_parsing_case_insensitive"] = 1.0 if bool_ok else 0.0

        def_count = len(re.findall(r"^\s*def\s+\w+\(", script_text, flags=re.MULTILINE))
        has_docstring = ('"""' in script_text) or ("'''" in script_text)
        modular_ok = def_count >= 3 and has_docstring
        scores["script_modular_structure"] = 1.0 if modular_ok else 0.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()